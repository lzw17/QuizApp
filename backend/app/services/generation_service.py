"""Durable, resumable AI question generation."""
import asyncio
import logging
import os
from typing import List, Optional

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from ..config import settings
from ..models.question import (
    BankStatus,
    BatchStatus,
    GenerateTask,
    GenerationBatch,
    Question,
    QuestionBank,
    TaskStatus,
)
from ..utils.dedup import deduplicate_questions, jaccard_similarity
from ..utils.time import utc_now
from .ai_engine import classify_questions_tags, generate_from_chunk
from .doc_parser import parse_document, split_text_into_chunks

logger = logging.getLogger(__name__)


class GenerationCancelled(Exception):
    pass


def _status_is(value, expected) -> bool:
    return value in (expected, expected.value)


def recover_interrupted_tasks(db: Session) -> List[str]:
    """Reset interrupted tasks and return the ids that need re-enqueuing."""
    task_ids: List[str] = []
    tasks = db.query(GenerateTask).filter(
        GenerateTask.status.in_([TaskStatus.pending, TaskStatus.running]),
    ).all()
    for task in tasks:
        bank = db.get(QuestionBank, task.bank_id) if task.bank_id is not None else None
        batches = db.query(GenerationBatch).filter(
            GenerationBatch.task_id == task.id,
        ).all()
        source_available = bool(
            bank
            and (
                bank.source_type == "url"
                or batches
                or (bank.source_file and os.path.isfile(bank.source_file))
            )
        )
        if not bank or not _status_is(bank.status, BankStatus.pending) or not source_available:
            task.status = TaskStatus.failed
            task.message = "任务恢复失败，请重新提交资料"
            task.error = "generation source unavailable after restart"
            if bank and _status_is(bank.status, BankStatus.pending):
                bank.status = BankStatus.deleted
                bank.source_file = ""
                bank.source_type = ""
            for batch in batches:
                batch.status = BatchStatus.failed
                batch.source_text = None
                batch.error = "generation source unavailable after restart"
                batch.completed_at = utc_now()
            continue

        # The API and worker are independent processes. An API-only restart
        # must not reset a batch that a healthy worker is still processing.
        # Re-enqueueing uses a deterministic ARQ job id; if a new worker really
        # takes over, _begin_generation resets interrupted running batches.
        if _status_is(task.status, TaskStatus.pending):
            task.message = "等待 Worker 处理..."
            task.error = ""
        task_ids.append(task.id)
    if tasks:
        db.commit()
    return task_ids


def _begin_generation(db_factory, task_id: str) -> Optional[dict]:
    db: Session = db_factory()
    try:
        task = db.query(GenerateTask).filter(
            GenerateTask.id == task_id,
        ).with_for_update().first()
        bank = db.get(QuestionBank, task.bank_id) if task else None
        if not task:
            return None
        if _status_is(task.status, TaskStatus.done) or _status_is(task.status, TaskStatus.failed):
            return None
        if not bank or not _status_is(bank.status, BankStatus.pending):
            raise GenerationCancelled("题库已删除或状态已变更")
        db.query(GenerationBatch).filter(
            GenerationBatch.task_id == task_id,
            GenerationBatch.status == BatchStatus.running,
        ).update(
            {
                GenerationBatch.status: BatchStatus.pending,
                GenerationBatch.started_at: None,
            },
            synchronize_session=False,
        )
        task.status = TaskStatus.running
        task.message = "正在恢复生成..." if task.total_chunks else "正在解析文档..."
        task.error = ""
        db.commit()
        return {
            "bank_id": bank.id,
            "file_path": bank.source_file,
            "source_type": bank.source_type,
            "num_direct": task.num_direct or 3,
            "num_logic": task.num_logic or 2,
        }
    finally:
        db.close()


def _require_generation_active(db: Session, task_id: str, bank_id: int) -> GenerateTask:
    task = db.get(GenerateTask, task_id)
    bank = db.get(QuestionBank, bank_id)
    if (
        not task
        or not _status_is(task.status, TaskStatus.running)
        or not bank
        or not _status_is(bank.status, BankStatus.pending)
    ):
        raise GenerationCancelled("生成任务已终止")
    return task


def _check_generation_active(db_factory, task_id: str, bank_id: int) -> None:
    db: Session = db_factory()
    try:
        _require_generation_active(db, task_id, bank_id)
    finally:
        db.close()


def _batch_plan_exists(db_factory, task_id: str) -> bool:
    db: Session = db_factory()
    try:
        return db.query(GenerationBatch.id).filter(
            GenerationBatch.task_id == task_id,
        ).first() is not None
    finally:
        db.close()


def _set_generation_plan(
    db_factory,
    task_id: str,
    bank_id: int,
    chunks: List[str],
) -> None:
    db: Session = db_factory()
    try:
        task = db.query(GenerateTask).filter(
            GenerateTask.id == task_id,
        ).with_for_update().first()
        if not task:
            raise GenerationCancelled("生成任务不存在")
        _require_generation_active(db, task_id, bank_id)
        if db.query(GenerationBatch.id).filter(
            GenerationBatch.task_id == task_id,
        ).first():
            return
        for index, chunk in enumerate(chunks):
            db.add(GenerationBatch(
                task_id=task_id,
                bank_id=bank_id,
                batch_index=index,
                source_text=chunk,
            ))
        task.total_chunks = len(chunks)
        task.progress = max(task.progress or 0, 5)
        task.message = f"文档已分为 {len(chunks)} 个批次，开始出题..."
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _update_task_aggregate(db: Session, task: GenerateTask, message: str = "") -> None:
    status_counts = dict(
        db.query(GenerationBatch.status, sa_func.count(GenerationBatch.id)).filter(
            GenerationBatch.task_id == task.id,
        ).group_by(GenerationBatch.status).all()
    )
    processed = sum(
        int(status_counts.get(status, 0))
        for status in (BatchStatus.done, BatchStatus.failed, BatchStatus.skipped)
    )
    failed = int(status_counts.get(BatchStatus.failed, 0))
    generated = db.query(sa_func.count(Question.id)).filter(
        Question.bank_id == task.bank_id,
        Question.status == "active",
    ).scalar() or 0
    task.processed_chunks = processed
    task.failed_chunks = failed
    task.generated_count = int(generated)
    task.progress = max(
        task.progress or 0,
        5 + int(processed / task.total_chunks * 90) if task.total_chunks else 5,
    )
    task.message = message or f"已完成 {processed}/{task.total_chunks} 个批次..."


def _claim_batch(db_factory, task_id: str, bank_id: int, batch_id: int) -> Optional[dict]:
    db: Session = db_factory()
    try:
        task = db.query(GenerateTask).filter(
            GenerateTask.id == task_id,
        ).with_for_update().first()
        if not task:
            return None
        _require_generation_active(db, task_id, bank_id)
        batch = db.query(GenerationBatch).filter(
            GenerationBatch.id == batch_id,
            GenerationBatch.task_id == task_id,
            GenerationBatch.status == BatchStatus.pending,
        ).with_for_update().first()
        if not batch:
            return None
        generated = db.query(sa_func.count(Question.id)).filter(
            Question.bank_id == bank_id,
            Question.status == "active",
        ).scalar() or 0
        if generated >= settings.MAX_GENERATED_QUESTIONS:
            batch.status = BatchStatus.skipped
            batch.source_text = None
            batch.completed_at = utc_now()
            _update_task_aggregate(db, task, "已达到题目数量上限，跳过剩余批次...")
            db.commit()
            return None
        batch.status = BatchStatus.running
        batch.attempt_count = (batch.attempt_count or 0) + 1
        batch.started_at = utc_now()
        batch.error = ""
        payload = {
            "batch_index": batch.batch_index,
            "source_text": batch.source_text or "",
        }
        db.commit()
        return payload
    finally:
        db.close()


def _reset_batch_for_retry(db_factory, task_id: str, bank_id: int, batch_id: int, error: str) -> None:
    db: Session = db_factory()
    try:
        _require_generation_active(db, task_id, bank_id)
        batch = db.get(GenerationBatch, batch_id)
        if batch and _status_is(batch.status, BatchStatus.running):
            batch.status = BatchStatus.pending
            batch.error = error[:1000]
            batch.started_at = None
            db.commit()
    finally:
        db.close()


def _mark_batch_failed(db_factory, task_id: str, batch_id: int, error: str) -> None:
    db: Session = db_factory()
    try:
        task = db.query(GenerateTask).filter(
            GenerateTask.id == task_id,
        ).with_for_update().first()
        if not task or not _status_is(task.status, TaskStatus.running):
            return
        batch = db.get(GenerationBatch, batch_id)
        if batch and not _status_is(batch.status, BatchStatus.done):
            batch.status = BatchStatus.failed
            batch.error = error[:1000]
            batch.source_text = None
            batch.completed_at = utc_now()
            _update_task_aggregate(
                db,
                task,
                f"第 {batch.batch_index + 1} 个批次生成失败，继续处理...",
            )
            db.commit()
    finally:
        db.close()


def _persist_batch_questions(
    db_factory,
    task_id: str,
    bank_id: int,
    batch_id: int,
    questions: List[dict],
) -> int:
    """Persist questions and mark the batch done in one transaction."""
    db: Session = db_factory()
    try:
        task = db.query(GenerateTask).filter(
            GenerateTask.id == task_id,
        ).with_for_update().first()
        bank = db.query(QuestionBank).filter(
            QuestionBank.id == bank_id,
        ).with_for_update().first()
        batch = db.query(GenerationBatch).filter(
            GenerationBatch.id == batch_id,
            GenerationBatch.task_id == task_id,
        ).with_for_update().first()
        if (
            not task
            or not _status_is(task.status, TaskStatus.running)
            or not bank
            or not _status_is(bank.status, BankStatus.pending)
            or not batch
        ):
            raise GenerationCancelled("生成任务已终止")
        if _status_is(batch.status, BatchStatus.done):
            return batch.generated_count or 0
        if not _status_is(batch.status, BatchStatus.running):
            return 0

        existing_contents = [
            row.content for row in db.query(Question.content).filter(
                Question.bank_id == bank_id,
                Question.status == "active",
            ).all()
        ]
        accepted: List[dict] = []
        for question in deduplicate_questions(questions, threshold=0.7):
            content = str(question.get("content", ""))
            if any(jaccard_similarity(content, existing) >= 0.7 for existing in existing_contents):
                continue
            accepted.append(question)
            existing_contents.append(content)

        current_count = len(existing_contents) - len(accepted)
        remaining = max(0, settings.MAX_GENERATED_QUESTIONS - current_count)
        accepted = accepted[:remaining]
        next_order = db.query(sa_func.max(Question.order_index)).filter(
            Question.bank_id == bank_id,
        ).scalar()
        next_order = (next_order if next_order is not None else -1) + 1
        for index, question in enumerate(accepted):
            payload = dict(question)
            payload["bank_id"] = bank_id
            payload["order_index"] = next_order + index
            db.add(Question(**payload))
        db.flush()

        batch.status = BatchStatus.done
        batch.generated_count = len(accepted)
        batch.source_text = None
        batch.error = ""
        batch.completed_at = utc_now()
        _update_task_aggregate(db, task)
        db.commit()
        return len(accepted)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _mark_generation_cancelled(db_factory, task_id: str) -> None:
    db: Session = db_factory()
    try:
        task = db.get(GenerateTask, task_id)
        if task and not (
            _status_is(task.status, TaskStatus.failed)
            or _status_is(task.status, TaskStatus.done)
        ):
            task.status = TaskStatus.failed
            task.error = "generation cancelled"
            task.message = "题库已删除或任务已终止"
            db.query(GenerationBatch).filter(
                GenerationBatch.task_id == task_id,
                GenerationBatch.status.in_([BatchStatus.pending, BatchStatus.running]),
            ).update(
                {
                    GenerationBatch.status: BatchStatus.failed,
                    GenerationBatch.source_text: None,
                    GenerationBatch.error: "generation cancelled",
                    GenerationBatch.completed_at: utc_now(),
                },
                synchronize_session=False,
            )
            db.commit()
    finally:
        db.close()


def _finalize_generation(db_factory, task_id: str, bank_id: int, failure_message: str = "") -> None:
    db: Session = db_factory()
    try:
        task = db.query(GenerateTask).filter(
            GenerateTask.id == task_id,
        ).with_for_update().first()
        bank = db.query(QuestionBank).filter(
            QuestionBank.id == bank_id,
        ).with_for_update().first()
        if not task or not bank or not _status_is(task.status, TaskStatus.running):
            return
        if failure_message:
            db.query(GenerationBatch).filter(
                GenerationBatch.task_id == task_id,
                GenerationBatch.status.in_([BatchStatus.pending, BatchStatus.running]),
            ).update(
                {
                    GenerationBatch.status: BatchStatus.failed,
                    GenerationBatch.source_text: None,
                    GenerationBatch.error: failure_message[:1000],
                    GenerationBatch.completed_at: utc_now(),
                },
                synchronize_session=False,
            )

        failed = db.query(GenerationBatch).filter(
            GenerationBatch.task_id == task_id,
            GenerationBatch.status == BatchStatus.failed,
        ).count()
        generated = db.query(sa_func.count(Question.id)).filter(
            Question.bank_id == bank_id,
            Question.status == "active",
        ).scalar() or 0
        total = db.query(GenerationBatch).filter(
            GenerationBatch.task_id == task_id,
        ).count()
        completed = db.query(GenerationBatch).filter(
            GenerationBatch.task_id == task_id,
            GenerationBatch.status.in_([
                BatchStatus.done,
                BatchStatus.failed,
                BatchStatus.skipped,
            ]),
        ).count()
        partial = failed > 0 or completed < total
        usable = generated > 0 and (
            not partial or generated >= settings.MIN_PARTIAL_GENERATED_QUESTIONS
        )
        if usable:
            bank.status = BankStatus.ready
            bank.total_count = int(generated)
            task.status = TaskStatus.done
            task.progress = 100
            task.processed_chunks = completed
            task.failed_chunks = failed
            task.generated_count = int(generated)
            task.partial_success = partial
            task.error = ""
            if partial:
                task.message = f"已生成 {generated} 道题，{failed} 个批次失败，可先开始练习"
            else:
                task.message = f"出题完成！共生成 {generated} 道题目"
        else:
            db.query(Question).filter(
                Question.bank_id == bank_id,
                Question.status == "active",
            ).update({Question.status: "deleted"}, synchronize_session=False)
            bank.status = BankStatus.deleted
            bank.total_count = 0
            bank.source_file = ""
            bank.source_type = ""
            task.status = TaskStatus.failed
            task.progress = min(task.progress or 0, 99)
            task.processed_chunks = completed
            task.failed_chunks = failed
            task.generated_count = 0
            task.partial_success = False
            task.error = "生成失败，请更换资料或稍后重试"
            task.message = failure_message or "未能生成足够的有效题目，请更换资料后重试"
        db.query(GenerationBatch).filter(
            GenerationBatch.task_id == task_id,
        ).update({GenerationBatch.source_text: None}, synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _cleanup_uploaded_source(file_path: str, source_type: str) -> None:
    if source_type == "url" or not file_path or not os.path.isfile(file_path):
        return
    try:
        os.remove(file_path)
    except OSError:
        logger.warning("无法清理源文件 %s", file_path, exc_info=True)


def _clear_uploaded_source_reference(
    db_factory,
    bank_id: int,
    file_path: str,
    source_type: str,
) -> None:
    _cleanup_uploaded_source(file_path, source_type)
    if source_type == "url":
        return
    db: Session = db_factory()
    try:
        bank = db.get(QuestionBank, bank_id)
        if bank and bank.source_file == file_path:
            bank.source_file = ""
            db.commit()
    finally:
        db.close()


def _cleanup_source_if_safe(
    db_factory,
    task_id: str,
    bank_id: int,
    file_path: str,
    source_type: str,
) -> None:
    db: Session = db_factory()
    try:
        task = db.get(GenerateTask, task_id)
        has_batches = db.query(GenerationBatch.id).filter(
            GenerationBatch.task_id == task_id,
        ).first() is not None
        terminal = bool(task and task.status in (TaskStatus.done, TaskStatus.failed))
    finally:
        db.close()
    if has_batches or terminal:
        _clear_uploaded_source_reference(db_factory, bank_id, file_path, source_type)


def _pending_batch_ids(db_factory, task_id: str) -> List[int]:
    db: Session = db_factory()
    try:
        return [
            row.id for row in db.query(GenerationBatch.id).filter(
                GenerationBatch.task_id == task_id,
                GenerationBatch.status == BatchStatus.pending,
            ).order_by(GenerationBatch.batch_index).all()
        ]
    finally:
        db.close()


async def _process_generation_batch(
    task_id: str,
    bank_id: int,
    batch_id: int,
    db_factory,
    num_direct: int,
    num_logic: int,
) -> None:
    max_attempts = settings.GENERATION_BATCH_MAX_RETRIES + 1
    for attempt in range(max_attempts):
        batch = await asyncio.to_thread(_claim_batch, db_factory, task_id, bank_id, batch_id)
        if not batch:
            return
        try:
            if not batch["source_text"].strip():
                raise ValueError("批次内容为空")
            async with asyncio.timeout(settings.GENERATION_BATCH_TIMEOUT_SECONDS):
                questions = await generate_from_chunk(
                    chunk=batch["source_text"],
                    bank_id=bank_id,
                    start_index=batch["batch_index"] * (num_direct + num_logic),
                    num_direct=num_direct,
                    num_logic=num_logic,
                )
                if not questions:
                    raise ValueError("模型未返回有效题目")
                questions = await classify_questions_tags(questions)
                await asyncio.to_thread(
                    _persist_batch_questions,
                    db_factory,
                    task_id,
                    bank_id,
                    batch_id,
                    questions,
                )
            return
        except GenerationCancelled:
            raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            if attempt + 1 < max_attempts:
                await asyncio.to_thread(
                    _reset_batch_for_retry,
                    db_factory,
                    task_id,
                    bank_id,
                    batch_id,
                    error,
                )
                await asyncio.sleep(min(2 ** attempt, 5))
                continue
            logger.warning("出题批次 %s 最终失败: %s", batch_id, error)
            await asyncio.to_thread(
                _mark_batch_failed,
                db_factory,
                task_id,
                batch_id,
                error,
            )


async def _run_generation_pipeline(
    task_id: str,
    bank_id: int,
    file_path: str,
    source_type: str,
    db_factory,
    num_direct: int,
    num_logic: int,
) -> None:
    if not await asyncio.to_thread(_batch_plan_exists, db_factory, task_id):
        text = await parse_document(file_path, source_type)
        await asyncio.to_thread(_check_generation_active, db_factory, task_id, bank_id)
        if not text.strip():
            raise ValueError("文档内容为空，请检查文件")
        chunks = await asyncio.to_thread(split_text_into_chunks, text)
        if not chunks:
            raise ValueError("文档内容不足，无法生成题目")
        if len(chunks) > settings.MAX_GENERATION_CHUNKS:
            raise ValueError(
                f"文档内容过长，最多支持 {settings.MAX_GENERATION_CHUNKS} 个文本分块"
            )
        await asyncio.to_thread(
            _set_generation_plan,
            db_factory,
            task_id,
            bank_id,
            chunks,
        )
        await asyncio.to_thread(
            _clear_uploaded_source_reference,
            db_factory,
            bank_id,
            file_path,
            source_type,
        )

    batch_ids = await asyncio.to_thread(_pending_batch_ids, db_factory, task_id)
    semaphore = asyncio.Semaphore(max(1, settings.GENERATION_CHUNK_CONCURRENCY))

    async def process(batch_id: int) -> None:
        async with semaphore:
            await _process_generation_batch(
                task_id,
                bank_id,
                batch_id,
                db_factory,
                num_direct,
                num_logic,
            )

    results = await asyncio.gather(
        *(process(batch_id) for batch_id in batch_ids),
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, BaseException):
            raise result
    await asyncio.to_thread(_finalize_generation, db_factory, task_id, bank_id)


async def run_generate_task(task_id: str, db_factory) -> None:
    """Run or resume one bounded generation job outside the API request."""
    try:
        context = await asyncio.to_thread(_begin_generation, db_factory, task_id)
    except GenerationCancelled:
        await asyncio.to_thread(_mark_generation_cancelled, db_factory, task_id)
        return
    if not context:
        return
    bank_id = context["bank_id"]
    try:
        async with asyncio.timeout(settings.GENERATION_TIMEOUT_SECONDS):
            await _run_generation_pipeline(
                task_id,
                bank_id,
                context["file_path"],
                context["source_type"],
                db_factory,
                context["num_direct"],
                context["num_logic"],
            )
    except GenerationCancelled:
        await asyncio.to_thread(_mark_generation_cancelled, db_factory, task_id)
    except asyncio.CancelledError:
        logger.info("出题任务 %s 被中断，将由持久化队列恢复", task_id)
        raise
    except TimeoutError:
        logger.error("出题任务 %s 超过 %s 秒", task_id, settings.GENERATION_TIMEOUT_SECONDS)
        await asyncio.to_thread(
            _finalize_generation,
            db_factory,
            task_id,
            bank_id,
            "出题达到时间上限",
        )
    except Exception as exc:
        logger.error("出题任务 %s 失败: %s", task_id, exc, exc_info=True)
        await asyncio.to_thread(
            _finalize_generation,
            db_factory,
            task_id,
            bank_id,
            "出题过程异常终止",
        )
    finally:
        await asyncio.to_thread(
            _cleanup_source_if_safe,
            db_factory,
            task_id,
            bank_id,
            context["file_path"],
            context["source_type"],
        )
