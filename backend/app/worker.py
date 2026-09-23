"""ARQ worker entry point for durable AI question generation."""
from .config import settings
from .database import SessionLocal
from .services.generation_service import run_generate_task
from .task_queue import redis_settings


async def run_generation_job(ctx, task_id: str) -> None:
    await run_generate_task(task_id=task_id, db_factory=SessionLocal)


async def startup(ctx) -> None:
    settings.validate_runtime_security()


class WorkerSettings:
    functions = [run_generation_job]
    on_startup = startup
    redis_settings = redis_settings()
    queue_name = settings.ARQ_QUEUE_NAME
    max_jobs = settings.MAX_CONCURRENT_GENERATION_TASKS
    job_timeout = settings.GENERATION_TIMEOUT_SECONDS + 120
    max_tries = 3
    keep_result = 0
    health_check_interval = 30
