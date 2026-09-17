from pydantic_settings import BaseSettings
from typing import Optional
from urllib.parse import urlparse
import os
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class Settings(BaseSettings):
    APP_NAME: str = "智题学习笔记"
    APP_ENV: str = "development"
    SECRET_KEY: str = "dev-secret-key"
    JWT_ISSUER: str = "quizapp-api"
    DEBUG: bool = True
    APP_TIMEZONE: str = "Asia/Shanghai"

    # 数据库 - 开发默认用 SQLite，生产换 MySQL
    DATABASE_URL: str = "sqlite:///./quiz_app.db"

    # OpenAI-compatible LLM. LLM_* takes precedence; DEEPSEEK_* remains as a
    # backward-compatible fallback for existing deployments.
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = ""
    LLM_MODEL: str = ""
    LLM_TIMEOUT_SECONDS: float = 60.0
    LLM_MAX_RETRIES: int = 2
    LLM_MAX_TOKENS: int = 4096

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
    PUBLIC_BASE_URL: str = ""

    # MinerU 解析服务（可选）
    MINERU_API_KEY: Optional[str] = None
    MINERU_API_URL: str = "https://mineru.net/api/v4"

    # 文件上传
    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE_MB: int = 50
    MAX_URL_CONTENT_MB: int = 10
    MAX_DOCX_ENTRIES: int = 2000
    MAX_DOCX_TOTAL_UNCOMPRESSED_MB: int = 100
    MAX_DOCX_SINGLE_ENTRY_MB: int = 20
    MAX_DOCX_COMPRESSION_RATIO: int = 200
    MAX_PDF_PAGES: int = 300
    MAX_EXTRACTED_TEXT_CHARS: int = 1_000_000
    TASK_STALE_MINUTES: int = 60
    MAX_GENERATION_CHUNKS: int = 100
    MAX_GENERATED_QUESTIONS: int = 500
    MAX_ACTIVE_GENERATION_TASKS: int = 2
    MAX_CONCURRENT_GENERATION_TASKS: int = 2
    MAX_DAILY_GENERATION_TASKS: int = 10
    MIN_GENERATION_INTERVAL_SECONDS: int = 30
    GENERATION_TIMEOUT_SECONDS: int = 1800
    # 文本分块：块过小会让 LLM 调用次数成倍增加，出题极慢
    GENERATION_CHUNK_SIZE: int = 1500
    GENERATION_CHUNK_OVERLAP: int = 150
    # 单个任务内并行处理的段落数（网络等待为主，不影响小内存机器）
    GENERATION_CHUNK_CONCURRENCY: int = 3

    # CORS
    ALLOWED_ORIGINS: str = "*"

    class Config:
        env_file = ".env"
        extra = "ignore"

    @property
    def allowed_origins_list(self) -> list[str]:
        origins = self.ALLOWED_ORIGINS.strip()
        if origins == "*":
            return ["*"]
        return [o.strip() for o in origins.split(",") if o.strip()]

    @property
    def max_file_size_bytes(self) -> int:
        return self.MAX_FILE_SIZE_MB * 1024 * 1024

    @property
    def max_url_content_bytes(self) -> int:
        return self.MAX_URL_CONTENT_MB * 1024 * 1024

    @property
    def admin_openids_set(self) -> set[str]:
        return {value.strip() for value in self.ADMIN_OPENIDS.split(",") if value.strip()}

    @property
    def llm_api_key(self) -> str:
        return self.LLM_API_KEY.strip() or self.DEEPSEEK_API_KEY.strip()

    @property
    def llm_model(self) -> str:
        return self.LLM_MODEL.strip() or self.DEEPSEEK_MODEL.strip()

    @property
    def llm_base_url(self) -> str:
        value = (self.LLM_BASE_URL.strip() or self.DEEPSEEK_BASE_URL.strip()).rstrip("/")
        suffix = "/chat/completions"
        if value.lower().endswith(suffix):
            value = value[:-len(suffix)].rstrip("/")
        return value

    @staticmethod
    def _is_placeholder(value: str) -> bool:
        normalized = value.strip().lower()
        if not normalized:
            return True
        if normalized.startswith("<") and normalized.endswith(">"):
            return True
        return any(token in normalized for token in (
            "change_me",
            "changeme",
            "replace_me",
            "your-secret",
            "your_api_key",
            "your-api-key",
            "你的",
        ))

    def validate_runtime_security(self) -> None:
        """Fail fast when production authentication is configured unsafely."""
        if not self.APP_NAME.strip() or not self.JWT_ISSUER.strip():
            raise RuntimeError("APP_NAME and JWT_ISSUER must not be empty")
        if self.MAX_FILE_SIZE_MB <= 0 or self.MAX_URL_CONTENT_MB <= 0:
            raise RuntimeError("Upload size limits must be positive")
        document_limits = (
            self.MAX_DOCX_ENTRIES,
            self.MAX_DOCX_TOTAL_UNCOMPRESSED_MB,
            self.MAX_DOCX_SINGLE_ENTRY_MB,
            self.MAX_DOCX_COMPRESSION_RATIO,
            self.MAX_PDF_PAGES,
            self.MAX_EXTRACTED_TEXT_CHARS,
        )
        if any(value <= 0 for value in document_limits):
            raise RuntimeError("Document parsing limits must be positive")
        if self.TASK_STALE_MINUTES <= 0:
            raise RuntimeError("TASK_STALE_MINUTES must be positive")
        if self.MAX_GENERATION_CHUNKS <= 0 or self.MAX_GENERATED_QUESTIONS <= 0:
            raise RuntimeError("Generation limits must be positive")
        if self.MAX_ACTIVE_GENERATION_TASKS <= 0 or self.MAX_CONCURRENT_GENERATION_TASKS <= 0:
            raise RuntimeError("Generation concurrency limits must be positive")
        if self.MAX_DAILY_GENERATION_TASKS <= 0 or self.MIN_GENERATION_INTERVAL_SECONDS < 0:
            raise RuntimeError("Generation rate limits are invalid")
        if self.GENERATION_TIMEOUT_SECONDS <= 0:
            raise RuntimeError("GENERATION_TIMEOUT_SECONDS must be positive")
        if self.GENERATION_CHUNK_SIZE <= 0 or self.GENERATION_CHUNK_OVERLAP < 0:
            raise RuntimeError("Generation chunk settings must be positive")
        if self.GENERATION_CHUNK_OVERLAP >= self.GENERATION_CHUNK_SIZE:
            raise RuntimeError("GENERATION_CHUNK_OVERLAP must be smaller than GENERATION_CHUNK_SIZE")
        if self.GENERATION_CHUNK_CONCURRENCY <= 0:
            raise RuntimeError("GENERATION_CHUNK_CONCURRENCY must be positive")
        if (
            self.LLM_TIMEOUT_SECONDS <= 0
            or self.LLM_MAX_RETRIES < 0
            or self.LLM_MAX_TOKENS <= 0
        ):
            raise RuntimeError("LLM timeout, retry, and token limits are invalid")
        llm_overrides = (
            self.LLM_API_KEY.strip(),
            self.LLM_BASE_URL.strip(),
            self.LLM_MODEL.strip(),
        )
        if any(llm_overrides) and not all(llm_overrides):
            raise RuntimeError(
                "LLM_API_KEY, LLM_BASE_URL, and LLM_MODEL must be configured together"
            )
        if not self.llm_model:
            raise RuntimeError("LLM_MODEL is required")
        llm_url = urlparse(self.llm_base_url)
        if (
            llm_url.scheme not in ("http", "https")
            or not llm_url.netloc
            or llm_url.username
            or llm_url.password
            or llm_url.query
            or llm_url.fragment
        ):
            raise RuntimeError("LLM_BASE_URL must be a valid HTTP(S) API base URL")
        try:
            ZoneInfo(self.APP_TIMEZONE)
        except ZoneInfoNotFoundError as exc:
            raise RuntimeError("APP_TIMEZONE must be a valid IANA timezone") from exc
        if self.APP_ENV.lower() not in ("prod", "production"):
            return
        if self.WX_MOCK_LOGIN:
            raise RuntimeError("WX_MOCK_LOGIN must be disabled in production")
        if self._is_placeholder(self.WX_APPID) or self._is_placeholder(self.WX_SECRET):
            raise RuntimeError("WX_APPID and WX_SECRET are required in production")
        if not re.fullmatch(r"wx[0-9a-fA-F]{16}", self.WX_APPID.strip()):
            raise RuntimeError("WX_APPID format is invalid")
        if not re.fullmatch(r"[0-9a-zA-Z]{32}", self.WX_SECRET.strip()):
            raise RuntimeError("WX_SECRET format is invalid")
        if self._is_placeholder(self.llm_api_key):
            raise RuntimeError("LLM_API_KEY is required in production")
        if llm_url.scheme != "https":
            raise RuntimeError("LLM_BASE_URL must use HTTPS in production")
        if len(self.SECRET_KEY) < 32 or self._is_placeholder(self.SECRET_KEY) or self.SECRET_KEY in (
            "dev-secret-key",
            "your-secret-key-change-in-production",
        ):
            raise RuntimeError("SECRET_KEY must be a random value of at least 32 characters")
        if self.DEBUG:
            raise RuntimeError("DEBUG must be disabled in production")
        if self.ALLOWED_ORIGINS.strip() == "*":
            raise RuntimeError("ALLOWED_ORIGINS must list explicit origins in production")
        if self.DATABASE_URL.lower().startswith("sqlite"):
            raise RuntimeError("SQLite is not supported in production; configure MySQL")
        database_url = urlparse(self.DATABASE_URL)
        if (
            not database_url.scheme.startswith("mysql")
            or not database_url.hostname
            or not database_url.username
            or not database_url.password
            or self._is_placeholder(self.DATABASE_URL)
        ):
            raise RuntimeError("DATABASE_URL must contain a complete MySQL connection in production")
        public_base_url = self.PUBLIC_BASE_URL.strip()
        if not public_base_url:
            raise RuntimeError("PUBLIC_BASE_URL is required in production")
        parsed = urlparse(public_base_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/"):
            raise RuntimeError("PUBLIC_BASE_URL must be an HTTPS origin")


settings = Settings()

# 确保上传目录存在
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
os.makedirs(os.path.join(settings.UPLOAD_DIR, "avatars"), exist_ok=True)
