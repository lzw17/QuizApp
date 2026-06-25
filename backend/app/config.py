from pydantic_settings import BaseSettings
from typing import Optional
import os


class Settings(BaseSettings):
    APP_NAME: str = "QuizApp"
    APP_ENV: str = "development"
    SECRET_KEY: str = "dev-secret-key"
    DEBUG: bool = True

    # 数据库 - 开发默认用 SQLite，生产换 MySQL
    DATABASE_URL: str = "sqlite:///./quiz_app.db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # DeepSeek
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-chat"

    # MinerU 解析服务（可选）
    MINERU_API_KEY: Optional[str] = None
    MINERU_API_URL: str = "https://mineru.net/api/v4"

    # 文件上传
    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE_MB: int = 50

    # CORS
    ALLOWED_ORIGINS: str = "*"

    class Config:
        env_file = ".env"
        extra = "ignore"

    @property
    def allowed_origins_list(self) -> list[str]:
        if self.ALLOWED_ORIGINS == "*":
            return ["*"]
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]

    @property
    def max_file_size_bytes(self) -> int:
        return self.MAX_FILE_SIZE_MB * 1024 * 1024


settings = Settings()

# 确保上传目录存在
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
