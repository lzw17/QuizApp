"""Generation queue lifecycle shared by the API process."""
import asyncio
import logging
from typing import Optional

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from .config import settings

logger = logging.getLogger(__name__)

_redis_pool: Optional[ArqRedis] = None
_local_tasks: dict[str, asyncio.Task] = {}


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(settings.REDIS_URL)


async def init_task_queue() -> None:
    global _redis_pool
    if settings.GENERATION_QUEUE_MODE.strip().lower() != "arq":
        return
    _redis_pool = await create_pool(
        redis_settings(),
        default_queue_name=settings.ARQ_QUEUE_NAME,
    )
    await _redis_pool.ping()


async def close_task_queue() -> None:
    global _redis_pool
    local_tasks = list(_local_tasks.values())
    for task in local_tasks:
        task.cancel()
    if local_tasks:
        await asyncio.gather(*local_tasks, return_exceptions=True)
    _local_tasks.clear()
    if _redis_pool is not None:
        await _redis_pool.aclose()
        _redis_pool = None


def _local_task_finished(task_id: str, task: asyncio.Task) -> None:
    _local_tasks.pop(task_id, None)
    if task.cancelled():
        return
    exception = task.exception()
    if exception:
        logger.error(
            "Local generation task %s crashed",
            task_id,
            exc_info=(type(exception), exception, exception.__traceback__),
        )


async def enqueue_generation_task(task_id: str) -> None:
    """Enqueue one task idempotently in production or run it locally in development."""
    mode = settings.GENERATION_QUEUE_MODE.strip().lower()
    if mode == "arq":
        if _redis_pool is None:
            raise RuntimeError("Generation queue is not initialized")
        await _redis_pool.enqueue_job(
            "run_generation_job",
            task_id,
            _job_id=f"generation:{task_id}",
            _queue_name=settings.ARQ_QUEUE_NAME,
        )
        return

    existing = _local_tasks.get(task_id)
    if existing and not existing.done():
        return

    from .database import SessionLocal
    from .services.generation_service import run_generate_task

    task = asyncio.create_task(
        run_generate_task(task_id=task_id, db_factory=SessionLocal),
        name=f"generation:{task_id}",
    )
    _local_tasks[task_id] = task
    task.add_done_callback(lambda completed: _local_task_finished(task_id, completed))


async def task_queue_healthy() -> bool:
    if settings.GENERATION_QUEUE_MODE.strip().lower() != "arq":
        return True
    if _redis_pool is None:
        return False
    try:
        if not await _redis_pool.ping():
            return False
        return bool(await _redis_pool.exists(f"{settings.ARQ_QUEUE_NAME}:health-check"))
    except Exception:
        logger.warning("Redis health check failed", exc_info=True)
        return False
