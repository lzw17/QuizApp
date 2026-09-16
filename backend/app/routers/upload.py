"""
文件上传 & AI 出题任务路由
POST /api/upload        上传文件，触发出题任务
POST /api/upload/url    提交 URL，触发出题任务
GET  /api/task/{id}     查询任务进度
GET  /api/task/{id}/sse SSE 实时推送进度
"""
import os
import uuid
import asyncio
import socket
from urllib.parse import urlparse
import ipaddress
import aiofiles
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db, SessionLocal
from ..models.question import GenerateTask, QuestionBank
from ..models.user import User
from ..schemas.question import UploadResponse, GenerateTaskOut
from ..schemas.question import QuestionBankCreate
from ..services.question_service import run_generate_task
from ..config import settings

router = APIRouter(prefix="/api", tags=["upload"])

ALLOWED_EXTENSIONS = {".pdf", ".docx"}
_generation_admission_lock = asyncio.Lock()


def _ensure_generation_capacity(db: Session, current_user: User) -> None:
    """Limit concurrent AI jobs per user before accepting more input."""
    active = db.query(GenerateTask.id).join(
        QuestionBank, QuestionBank.id == GenerateTask.bank_id
    ).filter(
        QuestionBank.created_by == current_user.openid,
        GenerateTask.status.in_(["pending", "running"]),
    ).count()
    if active >= settings.MAX_ACTIVE_GENERATION_TASKS:
        raise HTTPException(429, "当前已有任务正在生成，请稍后再试")


def _create_generation_records(
    db: Session,
    task_id: str,
    bank_data: QuestionBankCreate,
    current_user: User,
    source_file: str,
    source_type: str,
    message: str,
) -> QuestionBank:
    """Create the bank and task in one transaction after capacity admission."""
    bank = QuestionBank(
        name=bank_data.name,
        description=bank_data.description,
        category=bank_data.category,
        status="pending",
        source_file=source_file,
        source_type=source_type,
        created_by=current_user.openid,
    )
    db.add(bank)
    db.flush()
    db.add(GenerateTask(
        id=task_id,
        bank_id=bank.id,
        message=message,
    ))
    db.commit()
    db.refresh(bank)
    return bank


class UrlUploadRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    bank_name: str = Field(default="", max_length=200)
    bank_description: str = Field(default="", max_length=5000)
    bank_category: str = Field(default="", max_length=100)
    num_direct: int = Field(default=3, ge=1, le=8)
    num_logic: int = Field(default=2, ge=0, le=8)


def _validate_source_url(value: str) -> str:
    url = value.strip()
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
    except ValueError:
        raise HTTPException(400, "请输入有效的 HTTP/HTTPS URL")
    if parsed.scheme not in ("http", "https") or not hostname or parsed.username or parsed.password:
        raise HTTPException(400, "请输入有效的 HTTP/HTTPS URL")
    hostname = hostname.rstrip(".").lower()
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
        raise HTTPException(400, "不允许访问本地地址")
    addresses = set()
    try:
        addresses.update(
            ipaddress.ip_address(info[4][0])
            for info in socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        )
    except (OSError, ValueError):
        raise HTTPException(400, "无法解析目标地址")
    if any(address.is_private or address.is_loopback or address.is_link_local or address.is_reserved for address in addresses):
        raise HTTPException(400, "不允许访问内网地址")
    return url


async def _save_upload(file: UploadFile, save_path: str) -> None:
    total = 0
    try:
        async with aiofiles.open(save_path, "wb") as target:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > settings.max_file_size_bytes:
                    raise HTTPException(400, f"文件大小超过限制 {settings.MAX_FILE_SIZE_MB}MB")
                await target.write(chunk)
    except Exception:
        try:
            os.remove(save_path)
        except FileNotFoundError:
            pass
        raise


def _validate_file_signature(save_path: str, source_type: str) -> None:
    """Reject files whose content does not match the declared document type."""
    with open(save_path, "rb") as source:
        header = source.read(8)
    if source_type == "pdf" and not header.startswith(b"%PDF-"):
        raise HTTPException(400, "文件内容不是有效的 PDF")
    if source_type == "word" and not header.startswith(b"PK"):
        raise HTTPException(400, "文件内容不是有效的 DOCX")


def _get_source_type(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf":
        return "pdf"
    elif ext == ".docx":
        return "word"
    return "unknown"


@router.post("/upload", response_model=UploadResponse)
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    bank_name: str = Form("", max_length=200),
    bank_description: str = Form("", max_length=5000),
    bank_category: str = Form("", max_length=100),
    num_direct: int = Form(3, ge=1, le=8),
    num_logic: int = Form(2, ge=0, le=8),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上传 PDF/DOCX 文档，异步生成题库"""
    _ensure_generation_capacity(db, current_user)
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, "不支持的文件类型，仅支持: .pdf, .docx")

    source_type = _get_source_type(file.filename or "")

    # 保存文件
    task_id = str(uuid.uuid4())
    save_path = os.path.join(settings.UPLOAD_DIR, f"{task_id}{ext}")
    await _save_upload(file, save_path)
    try:
        _validate_file_signature(save_path, source_type)
    except Exception:
        try:
            os.remove(save_path)
        except OSError:
            pass
        raise

    bank_data = QuestionBankCreate(
        name=bank_name or os.path.splitext(file.filename or "未命名")[0],
        description=bank_description,
        category=bank_category,
    )
    try:
        # The production image intentionally runs one API worker. This lock
        # closes the check/create race between concurrent uploads in that worker.
        async with _generation_admission_lock:
            _ensure_generation_capacity(db, current_user)
            bank = _create_generation_records(
                db,
                task_id,
                bank_data,
                current_user,
                save_path,
                source_type,
                "任务已创建，等待处理...",
            )
    except Exception:
        try:
            os.remove(save_path)
        except OSError:
            pass
        raise

    # 后台异步执行
    background_tasks.add_task(
        run_generate_task,
        task_id=task_id,
        bank_id=bank.id,
        file_path=save_path,
        source_type=source_type,
        db_factory=SessionLocal,
        num_direct=num_direct,
        num_logic=num_logic,
    )

    return UploadResponse(task_id=task_id, bank_id=bank.id, message="文件上传成功，正在生成题库...")


@router.post("/upload/url", response_model=UploadResponse)
async def upload_url(
    background_tasks: BackgroundTasks,
    data: UrlUploadRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """提交 URL，爬取页面内容并生成题库"""
    _ensure_generation_capacity(db, current_user)
    url = await asyncio.to_thread(_validate_source_url, data.url)

    task_id = str(uuid.uuid4())

    bank_data = QuestionBankCreate(
        name=data.bank_name or url[:50],
        description=data.bank_description,
        category=data.bank_category,
    )
    async with _generation_admission_lock:
        _ensure_generation_capacity(db, current_user)
        bank = _create_generation_records(
            db,
            task_id,
            bank_data,
            current_user,
            url,
            "url",
            "任务已创建...",
        )

    background_tasks.add_task(
        run_generate_task,
        task_id=task_id,
        bank_id=bank.id,
        file_path=url,
        source_type="url",
        db_factory=SessionLocal,
        num_direct=data.num_direct,
        num_logic=data.num_logic,
    )

    return UploadResponse(task_id=task_id, bank_id=bank.id, message="URL 提交成功，正在生成题库...")


def _get_owned_task(db: Session, task_id: str, current_user: User) -> GenerateTask:
    task = db.query(GenerateTask).filter(GenerateTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    bank = db.query(QuestionBank).filter(QuestionBank.id == task.bank_id).first()
    if not current_user.is_admin and (not bank or bank.created_by != current_user.openid):
        raise HTTPException(403, "无权查看此任务")
    return task


def _public_task(task: GenerateTask) -> GenerateTaskOut:
    """Serialize task status without exposing legacy/provider exception text."""
    result = GenerateTaskOut.model_validate(task)
    if result.status == "failed":
        result.error = "生成失败，请更换资料或稍后重试"
    return result


@router.get("/task/{task_id}", response_model=GenerateTaskOut)
def get_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查询出题任务状态（轮询模式）"""
    return _public_task(_get_owned_task(db, task_id, current_user))


@router.get("/task/{task_id}/sse")
async def task_sse(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """SSE 实时推送出题进度"""
    import json

    _get_owned_task(db, task_id, current_user)

    def read_task_snapshot():
        poll_db = SessionLocal()
        try:
            task = poll_db.query(GenerateTask).filter(GenerateTask.id == task_id).first()
            if not task:
                return None
            return {
                "status": task.status,
                "progress": task.progress,
                "generated_count": task.generated_count,
                "message": task.message,
                "error": task.error,
            }
        finally:
            poll_db.close()

    async def event_generator():
        deadline = asyncio.get_running_loop().time() + max(60, settings.TASK_STALE_MINUTES * 60)
        while True:
            snapshot = await asyncio.to_thread(read_task_snapshot)
            if not snapshot:
                yield f"data: {json.dumps({'error': '任务不存在'})}\n\n"
                break

            payload = {
                "status": snapshot["status"],
                "progress": snapshot["progress"],
                "generated_count": snapshot["generated_count"],
                "message": snapshot["message"],
                "error": (
                    "生成失败，请更换资料或稍后重试"
                    if snapshot["status"] == "failed"
                    else snapshot["error"]
                ),
            }
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            if snapshot["status"] in ("done", "failed"):
                break

            if asyncio.get_running_loop().time() >= deadline:
                yield f"data: {json.dumps({'error': '任务状态查询超时'})}\n\n"
                break
            await asyncio.sleep(1.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
