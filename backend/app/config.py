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

    # WeChat Mini Program
    WX_APPID: str = ""
    WX_SECRET: str = ""
    WX_MOCK_LOGIN: bool = False
    WX_MOCK_OPENID: str = "local-dev-user"
    WX_MOCK_ADMIN: bool = False
    ADMIN_OPENIDS: str = ""
    AUTH_TOKEN_EXPIRE_DAYS: int = 30

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

    @property
    def admin_openids_set(self) -> set[str]:
        return {value.strip() for value in self.ADMIN_OPENIDS.split(",") if value.strip()}

    def validate_runtime_security(self) -> None:
        """Fail fast when production authentication is configured unsafely."""
        if self.APP_ENV.lower() not in ("prod", "production"):
            return
        if self.WX_MOCK_LOGIN:
            raise RuntimeError("WX_MOCK_LOGIN must be disabled in production")
        if not self.WX_APPID or not self.WX_SECRET:
            raise RuntimeError("WX_APPID and WX_SECRET are required in production")
        if len(self.SECRET_KEY) < 32 or self.SECRET_KEY in (
            "dev-secret-key",
            "your-secret-key-change-in-production",
        ):
            raise RuntimeError("SECRET_KEY must be a random value of at least 32 characters")


settings = Settings()

# 确保上传目录存在
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
