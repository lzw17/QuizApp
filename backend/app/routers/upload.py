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
from ..services.question_service import create_bank, run_generate_task
from ..config import settings

router = APIRouter(prefix="/api", tags=["upload"])

ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx"}


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
    if parsed.scheme not in ("http", "https") or not hostname:
        raise HTTPException(400, "请输入有效的 HTTP/HTTPS URL")
    hostname = hostname.rstrip(".").lower()
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
        raise HTTPException(400, "不允许访问本地地址")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address and (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved):
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


def _get_source_type(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf":
        return "pdf"
    elif ext in (".doc", ".docx"):
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
    """上传 PDF/Word 文档，异步生成题库"""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"不支持的文件类型，仅支持: {', '.join(ALLOWED_EXTENSIONS)}")

    source_type = _get_source_type(file.filename or "")

    # 保存文件
    task_id = str(uuid.uuid4())
    save_path = os.path.join(settings.UPLOAD_DIR, f"{task_id}{ext}")
    await _save_upload(file, save_path)

    # 创建题库
    bank_data = QuestionBankCreate(
        name=bank_name or os.path.splitext(file.filename or "未命名")[0],
        description=bank_description,
        category=bank_category,
    )
    bank = create_bank(db, bank_data)
    bank.source_file = save_path
    bank.source_type = source_type
    bank.created_by = current_user.openid
    db.commit()

    # 创建任务记录
    task = GenerateTask(id=task_id, bank_id=bank.id, message="任务已创建，等待处理...")
    db.add(task)
    db.commit()

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
    url = _validate_source_url(data.url)

    task_id = str(uuid.uuid4())

    bank_data = QuestionBankCreate(
        name=data.bank_name or url[:50],
        description=data.bank_description,
        category=data.bank_category,
    )
    bank = create_bank(db, bank_data)
    bank.source_file = url
    bank.source_type = "url"
    bank.created_by = current_user.openid
    db.commit()

    task = GenerateTask(id=task_id, bank_id=bank.id, message="任务已创建...")
    db.add(task)
    db.commit()

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


@router.get("/task/{task_id}", response_model=GenerateTaskOut)
def get_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查询出题任务状态（轮询模式）"""
    return _get_owned_task(db, task_id, current_user)


@router.get("/task/{task_id}/sse")
async def task_sse(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """SSE 实时推送出题进度"""
    import json

    _get_owned_task(db, task_id, current_user)

    async def event_generator():
        while True:
            poll_db = SessionLocal()
            try:
                task = poll_db.query(GenerateTask).filter(GenerateTask.id == task_id).first()
            finally:
                poll_db.close()
            if not task:
                yield f"data: {json.dumps({'error': '任务不存在'})}\n\n"
                break

            payload = {
                "status": task.status,
                "progress": task.progress,
                "generated_count": task.generated_count,
                "message": task.message,
                "error": task.error,
            }
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            if task.status in ("done", "failed"):
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
