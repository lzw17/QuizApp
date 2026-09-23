from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
import asyncio
import os

from .config import settings
from .database import create_tables, SessionLocal, engine
from .routers import upload, questions, practice, auth
from .services.generation_service import recover_interrupted_tasks
from .task_queue import (
    close_task_queue,
    enqueue_generation_task,
    init_task_queue,
    task_queue_healthy,
)

app = FastAPI(
    title=f"{settings.APP_NAME} API",
    description="微信刷题小程序后端服务",
    version="1.0.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
)

# CORS（微信小程序需要）
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=settings.ALLOWED_ORIGINS.strip() != "*",
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth.router)
app.include_router(upload.router)
app.include_router(questions.router)
app.include_router(practice.router)

# 挂载上传文件静态访问
avatar_dir = os.path.join(settings.UPLOAD_DIR, "avatars")
os.makedirs(avatar_dir, exist_ok=True)
app.mount("/uploads/avatars", StaticFiles(directory=avatar_dir), name="avatars")


@app.on_event("startup")
async def startup():
    settings.validate_runtime_security()
    create_tables()
    await init_task_queue()
    db = SessionLocal()
    try:
        interrupted_task_ids = recover_interrupted_tasks(db)
    finally:
        db.close()
    for task_id in interrupted_task_ids:
        await enqueue_generation_task(task_id)


@app.on_event("shutdown")
async def shutdown():
    await close_task_queue()


def _database_healthy() -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True


@app.get("/health")
async def health():
    """Report readiness for the database and durable generation queue."""
    database_ok, queue_ok = await asyncio.gather(
        asyncio.to_thread(_database_healthy),
        task_queue_healthy(),
    )
    if not database_ok or not queue_ok:
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "app": settings.APP_NAME,
                "database": "ok" if database_ok else "unavailable",
                "queue": "ok" if queue_ok else "unavailable",
            },
        )
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "database": "ok",
        "queue": "ok",
    }
