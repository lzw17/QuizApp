from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from .config import settings
from .database import create_tables
from .routers import upload, questions, practice, auth

app = FastAPI(
    title="QuizApp API",
    description="微信刷题小程序后端服务",
    version="1.0.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

# CORS（微信小程序需要）
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth.router)
app.include_router(upload.router)
app.include_router(questions.router)
app.include_router(practice.router)

# 挂载上传文件静态访问
if os.path.exists(settings.UPLOAD_DIR):
    app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")


@app.on_event("startup")
async def startup():
    create_tables()


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME}
