from sqlalchemy import create_engine, event
from sqlalchemy import inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from .config import settings

def _engine_options(database_url: str) -> dict:
    options = {"echo": settings.DEBUG}
    if database_url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
    else:
        # MySQL closes idle connections. Check pooled connections before use
        # and recycle them before the server's typical idle timeout.
        options.update(pool_pre_ping=True, pool_recycle=1800)
    return options


engine = create_engine(settings.DATABASE_URL, **_engine_options(settings.DATABASE_URL))


if not settings.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_mysql_session_timezone(dbapi_connection, _connection_record):
        """Keep server defaults and explicit application timestamps in UTC."""
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("SET time_zone = '+00:00'")
        finally:
            cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI 依赖注入：获取数据库 Session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    """初始化建表（开发用，生产建议用 Alembic 迁移）"""
    from .models import question, user  # noqa: F401 触发模型注册
    Base.metadata.create_all(bind=engine)
    # 开发环境常直接复用旧 SQLite 文件，补齐新增的 token 撤销字段。
    if settings.DATABASE_URL.startswith("sqlite"):
        columns = {column["name"] for column in inspect(engine).get_columns("users")}
        if "token_version" not in columns:
            with engine.begin() as connection:
                connection.execute(text(
                    "ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0"
                ))
        if "is_active" not in columns:
            with engine.begin() as connection:
                connection.execute(text(
                    "ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1"
                ))
        task_columns = {
            column["name"] for column in inspect(engine).get_columns("generate_tasks")
        }
        task_column_migrations = {
            "failed_chunks": (
                "ALTER TABLE generate_tasks ADD COLUMN failed_chunks INTEGER NOT NULL DEFAULT 0"
            ),
            "num_direct": (
                "ALTER TABLE generate_tasks ADD COLUMN num_direct INTEGER NOT NULL DEFAULT 3"
            ),
            "num_logic": (
                "ALTER TABLE generate_tasks ADD COLUMN num_logic INTEGER NOT NULL DEFAULT 2"
            ),
            "partial_success": (
                "ALTER TABLE generate_tasks ADD COLUMN partial_success INTEGER NOT NULL DEFAULT 0"
            ),
        }
        for column_name, statement in task_column_migrations.items():
            if column_name not in task_columns:
                with engine.begin() as connection:
                    connection.execute(text(statement))
