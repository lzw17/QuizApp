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
import aiofiles
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db, SessionLocal
from ..models.question import GenerateTask, QuestionBank
from ..schemas.question import UploadResponse, GenerateTaskOut
from ..schemas.question import QuestionBankCreate
from ..services.question_service import create_bank, run_generate_task
from ..config import settings

router = APIRouter(prefix="/api", tags=["upload"])

ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx"}


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
    bank_name: str = Form(""),
    bank_description: str = Form(""),
    bank_category: str = Form(""),
    num_direct: int = Form(3),
    num_logic: int = Form(2),
    db: Session = Depends(get_db),
):
    """上传 PDF/Word 文档，异步生成题库"""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"不支持的文件类型，仅支持: {', '.join(ALLOWED_EXTENSIONS)}")

    if file.size and file.size > settings.max_file_size_bytes:
        raise HTTPException(400, f"文件大小超过限制 {settings.MAX_FILE_SIZE_MB}MB")

    source_type = _get_source_type(file.filename or "")

    # 保存文件
    task_id = str(uuid.uuid4())
    save_path = os.path.join(settings.UPLOAD_DIR, f"{task_id}{ext}")
    async with aiofiles.open(save_path, "wb") as f:
        content = await file.read()
        await f.write(content)

    # 创建题库
    bank_data = QuestionBankCreate(
        name=bank_name or os.path.splitext(file.filename or "未命名")[0],
        description=bank_description,
        category=bank_category,
    )
    bank = create_bank(db, bank_data)
    bank.source_file = save_path
    bank.source_type = source_type
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
    url: str = Form(...),
    bank_name: str = Form(""),
    bank_description: str = Form(""),
    bank_category: str = Form(""),
    num_direct: int = Form(3),
    num_logic: int = Form(2),
    db: Session = Depends(get_db),
):
    """提交 URL，爬取页面内容并生成题库"""
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "请输入有效的 HTTP/HTTPS URL")

    task_id = str(uuid.uuid4())

    bank_data = QuestionBankCreate(
        name=bank_name or url[:50],
        description=bank_description,
        category=bank_category,
    )
    bank = create_bank(db, bank_data)
    bank.source_file = url
    bank.source_type = "url"
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
        num_direct=num_direct,
        num_logic=num_logic,
    )

    return UploadResponse(task_id=task_id, bank_id=bank.id, message="URL 提交成功，正在生成题库...")


@router.get("/task/{task_id}", response_model=GenerateTaskOut)
def get_task(task_id: str, db: Session = Depends(get_db)):
    """查询出题任务状态（轮询模式）"""
    task = db.query(GenerateTask).filter(GenerateTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


@router.get("/task/{task_id}/sse")
async def task_sse(task_id: str, db: Session = Depends(get_db)):
    """SSE 实时推送出题进度"""
    import json

    async def event_generator():
        while True:
            task = db.query(GenerateTask).filter(GenerateTask.id == task_id).first()
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
