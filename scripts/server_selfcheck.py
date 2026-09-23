# -*- coding: utf-8 -*-
"""服务端自检：新代码 + 新配置是否真正就绪。

在服务器上以项目用户身份运行（本脚本不含任何凭据）：

    cd /www/wwwroot/quizapp/backend
    sudo -u www /www/server/pyporject_evn/versions/3.11.16/bin/python3.11 \
        server_selfcheck.py

也可以先上传到 /tmp 再执行——脚本自己会把 BACKEND 插进 sys.path，
不依赖 CWD（Python 默认只把「脚本所在目录」而非 CWD 加进 sys.path，
放在 /tmp 下执行会报 No module named 'app'）。
"""
import sys

BACKEND = "/www/wwwroot/quizapp/backend"
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

print("=== 1. 生产配置校验（新代码必须 PASS）===")
from app.config import settings

settings.validate_runtime_security()
print("validate_runtime_security: PASS")
print("  APP_ENV       =", settings.APP_ENV)
print("  QUEUE_MODE    =", settings.GENERATION_QUEUE_MODE)
print("  ARQ_QUEUE     =", settings.ARQ_QUEUE_NAME)
print("  REDIS 目标     =", settings.REDIS_URL.split("@")[-1])
print("  BATCH_TIMEOUT =", settings.GENERATION_BATCH_TIMEOUT_SECONDS)
print("  BATCH_RETRIES =", settings.GENERATION_BATCH_MAX_RETRIES)
print("  MIN_PARTIAL   =", settings.MIN_PARTIAL_GENERATED_QUESTIONS)
print("  CHUNK_CONC    =", settings.GENERATION_CHUNK_CONCURRENCY)
print("  LLM_MODEL     =", settings.llm_model)
print("  LLM_BASE_URL  =", settings.llm_base_url)

print()
print("=== 2. 新模块 import ===")
import app.main  # noqa: F401
from app.services import generation_service  # noqa: F401
from app import task_queue  # noqa: F401
from app.worker import WorkerSettings as W

print("import app.main / generation_service / task_queue: OK")

print()
print("=== 3. WorkerSettings 关键参数（与 arq 契约核对）===")
print("  functions     =", [f.__name__ for f in W.functions])
print("  queue_name    =", repr(W.queue_name))
print("  job_timeout   =", W.job_timeout)
print("  max_jobs      =", W.max_jobs)
print("  max_tries     =", W.max_tries)
print("  keep_result   =", W.keep_result)
print("  health_check_interval =", W.health_check_interval)
print("  redis host    =", W.redis_settings.host, "port =", W.redis_settings.port,
      "password? =", bool(W.redis_settings.password))
print("  health_key    =", W.queue_name + ":health-check", "(task_queue.py 里查的就是这个键)")

print()
print("=== 4. 表结构 vs ORM 模型一致性 ===")
from sqlalchemy import inspect

from app.database import engine

insp = inspect(engine)
task_cols = {c["name"] for c in insp.get_columns("generate_tasks")}
need = {"failed_chunks", "num_direct", "num_logic", "partial_success"}
print("  generate_tasks 新列齐备 =", need.issubset(task_cols), "缺失 =", need - task_cols)
print("  generation_batches 表存在 =", insp.has_table("generation_batches"))
batch_cols = ({c["name"] for c in insp.get_columns("generation_batches")}
              if insp.has_table("generation_batches") else set())
from app.models.question import GenerationBatch

model_cols = {c.name for c in GenerationBatch.__table__.columns}
print("  GenerationBatch 模型列 =", sorted(model_cols))
print("  模型列全部落库 =", model_cols.issubset(batch_cols), "缺失 =", model_cols - batch_cols)

print()
print("=== 5. Redis 连通性（应用自己的池）===")
import asyncio

from app.task_queue import close_task_queue, init_task_queue, task_queue_healthy


async def check():
    await init_task_queue()
    ok = await task_queue_healthy()
    print("  init_task_queue + ping: OK")
    print("  task_queue_healthy() =", ok, "（worker 未启动时预期 False）")
    import arq

    from app.task_queue import _redis_pool

    print("  redis 客户端 =", arq.__name__, "pool =", type(_redis_pool).__name__)
    await close_task_queue()


asyncio.run(check())
print()
print(">>> 服务端自检全部完成")
sys.exit(0)
