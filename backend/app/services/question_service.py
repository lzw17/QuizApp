"""
题库和答题业务逻辑
"""
import uuid
import asyncio
import logging
import os
from datetime import date, datetime, timedelta
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, func as sa_func
from sqlalchemy.exc import IntegrityError

from ..models.question import QuestionBank, Question, GenerateTask, TaskStatus, BankStatus
from ..models.user import User, UserProgress, AnswerRecord
from ..schemas.question import QuestionBankCreate, QuestionCreate
from ..schemas.user import AnswerSubmit, AnswerResult
from ..services.doc_parser import parse_document, split_text_into_chunks
from ..services.ai_engine import generate_questions_from_chunks, classify_questions_tags

logger = logging.getLogger(__name__)


class GenerationCancelled(Exception):
    pass


def evaluate_answer(question: Question, raw_answer: str) -> tuple[str, bool]:
    """Normalize and validate one answer without writing any database records."""
    allowed_keys = {str(item.get("key", "")).strip().upper() for item in (question.options or [])}
    correct_answer = "".join(str(question.answer or "").split()).upper()
    user_answer = "".join(str(raw_answer or "").split()).upper()
    if not allowed_keys or not correct_answer:
        raise ValueError("题目选项或标准答案无效")
    if any(key not in allowed_keys for key in user_answer):
        raise ValueError("答案包含无效选项")
    if len(set(user_answer)) != len(user_answer):
        raise ValueError("答案不能包含重复选项")
    if question.type in ("single", "judge") and len(user_answer) != 1:
        raise ValueError("单选题和判断题只能选择一个答案")
    if question.type == "multi" and not user_answer:
        raise ValueError("多选题至少选择一个答案")
    is_correct = (
        user_answer == correct_answer
        if question.type in ("single", "judge")
        else set(user_answer) == set(correct_answer)
    )
    return user_answer, is_correct


def _get_or_create_progress(db: Session, user_id: int, bank_id: int) -> UserProgress:
    progress = db.query(UserProgress).filter(
        UserProgress.user_id == user_id,
        UserProgress.bank_id == bank_id,
    ).first()
    if progress:
        return progress

    try:
        with db.begin_nested():
            progress = UserProgress(user_id=user_id, bank_id=bank_id, starred_ids=[])
            db.add(progress)
            db.flush()
    except IntegrityError:
        progress = db.query(UserProgress).filter(
            UserProgress.user_id == user_id,
            UserProgress.bank_id == bank_id,
        ).first()
        if not progress:
            raise
    return progress


# ──────────────────────────────────────────
#  题库 CRUD
# ──────────────────────────────────────────

def create_bank(db: Session, data: QuestionBankCreate, created_by: str = "") -> QuestionBank:
    bank = QuestionBank(
        name=data.name,
        description=data.description,
        category=data.category,
        status=BankStatus.pending,
        created_by=created_by,
    )
    db.add(bank)
    db.commit()
    db.refresh(bank)
    return bank


def get_banks(db: Session, skip: int = 0, limit: int = 20) -> List[QuestionBank]:
    return db.query(QuestionBank).filter(
        QuestionBank.status == BankStatus.ready
    ).order_by(QuestionBank.id.desc()).offset(skip).limit(limit).all()


def get_bank(db: Session, bank_id: int) -> Optional[QuestionBank]:
    return db.query(QuestionBank).filter(QuestionBank.id == bank_id).first()


# ──────────────────────────────────────────
#  题目查询
# ──────────────────────────────────────────

def get_questions(
    db: Session,
    bank_id: int,
    mode: str = "sequential",
    tag: Optional[str] = None,
    difficulty: Optional[int] = None,
    skip: int = 0,
    limit: int = 20,
) -> List[Question]:
    query = db.query(Question).join(QuestionBank).filter(
        Question.bank_id == bank_id,
        Question.status == "active",
        QuestionBank.status == BankStatus.ready,
    )
    if tag:
        query = query.filter(Question.tags.contains(tag))
    if difficulty:
        query = query.filter(Question.difficulty == difficulty)

    if mode == "random":
        query = query.order_by(sa_func.random())
    else:
        query = query.order_by(Question.order_index)

    return query.offset(skip).limit(limit).all()


def get_wrong_questions(db: Session, user_id: int, bank_id: Optional[int] = None) -> List[dict]:
    """获取用户错题，每道题只取最近一次错误记录"""
    query = db.query(AnswerRecord).filter(
        AnswerRecord.user_id == user_id,
        AnswerRecord.is_correct == False,
    )
    if bank_id:
        query = query.filter(AnswerRecord.bank_id == bank_id)

    # 按题目去重，保留最新
    records = query.order_by(AnswerRecord.answered_at.desc()).all()
    seen = set()
    unique = []
    for r in records:
        if r.question_id not in seen:
            seen.add(r.question_id)
            unique.append(r)

    latest = get_latest_answer_records(db, user_id, bank_id)
    unique = [record for record in latest.values() if not record.is_correct]
    unique.sort(key=lambda record: record.answered_at or datetime.min, reverse=True)

    results = []
    for record in unique[:100]:
        q = db.query(Question).join(QuestionBank).filter(
            Question.id == record.question_id,
            Question.status == "active",
            QuestionBank.status == BankStatus.ready,
        ).first()
        if q:
            results.append({
                "record_id": record.id,
                "question_id": record.question_id,
                "bank_id": record.bank_id,
                "user_answer": record.user_answer,
                "answered_at": record.answered_at.isoformat(),
                "question": {
                    "id": q.id,
                    "type": q.type,
                    "content": q.content,
                    "options": q.options,
                    "answer": q.answer,
                    "explanation": q.explanation,
                    "tags": q.tags,
                    "difficulty": q.difficulty,
                },
            })
    return results


def get_latest_answer_records(
    db: Session,
    user_id: int,
    bank_id: Optional[int] = None,
) -> dict[int, AnswerRecord]:
    """Get the latest answer attempt for each question owned by a user."""
    query = db.query(AnswerRecord).filter(AnswerRecord.user_id == user_id)
    if bank_id:
        query = query.filter(AnswerRecord.bank_id == bank_id)
    records = query.order_by(
        AnswerRecord.answered_at.desc(),
        AnswerRecord.id.desc(),
    ).all()
    latest: dict[int, AnswerRecord] = {}
    for record in records:
        latest.setdefault(record.question_id, record)
    return latest


def get_current_wrong_question_ids(
    db: Session,
    user_id: int,
    bank_id: Optional[int] = None,
) -> List[int]:
    """Return question ids that are still wrong after the latest attempt."""
    latest = get_latest_answer_records(db, user_id, bank_id)
    records = [record for record in latest.values() if not record.is_correct]
    records.sort(key=lambda record: record.answered_at or datetime.min, reverse=True)
    return [record.question_id for record in records]


def get_review_questions(
    db: Session,
    user_id: int,
    bank_id: int,
    source: str,
) -> List[dict]:
    """Return answer-bearing questions only for the user's review set."""
    if source == "wrong":
        question_ids = get_current_wrong_question_ids(db, user_id, bank_id)
    elif source == "starred":
        progress = db.query(UserProgress).filter(
            UserProgress.user_id == user_id,
            UserProgress.bank_id == bank_id,
        ).first()
        question_ids = list(progress.starred_ids or []) if progress else []
    else:
        raise ValueError("source must be wrong or starred")

    if not question_ids:
        return []
    question_ids = question_ids[:100]
    questions = db.query(Question).join(QuestionBank).filter(
        Question.id.in_(question_ids),
        Question.bank_id == bank_id,
        Question.status == "active",
        QuestionBank.status == BankStatus.ready,
    ).all()
    by_id = {question.id: question for question in questions}
    return [
        {
            "id": question.id,
            "bank_id": question.bank_id,
            "type": question.type,
            "content": question.content,
            "options": question.options,
            "answer": question.answer,
            "explanation": question.explanation,
            "tags": question.tags,
            "difficulty": question.difficulty,
            "correct_rate": question.correct_rate,
            "order_index": question.order_index,
        }
        for question_id in question_ids
        if (question := by_id.get(question_id)) is not None
    ]


def get_starred_questions(db: Session, user_id: int, bank_id: int) -> List[Question]:
    progress = db.query(UserProgress).filter(
        UserProgress.user_id == user_id,
        UserProgress.bank_id == bank_id,
    ).first()
    if not progress or not progress.starred_ids:
        return []
    return db.query(Question).join(QuestionBank).filter(
        Question.id.in_(progress.starred_ids),
        Question.status == "active",
        QuestionBank.status == BankStatus.ready,
    ).all()


# ──────────────────────────────────────────
#  答题逻辑
# ──────────────────────────────────────────

def submit_answer(db: Session, data: AnswerSubmit, user_id: int) -> AnswerResult:
    question = db.query(Question).join(QuestionBank).filter(
        Question.id == data.question_id,
        Question.bank_id == data.bank_id,
        Question.status == "active",
        QuestionBank.status == BankStatus.ready,
    ).first()
    if not question:
        raise ValueError("题目不存在或不属于该题库")

    user_answer, is_correct = evaluate_answer(question, data.user_answer)

    # 写入答题记录
    record = AnswerRecord(
        user_id=user_id,
        question_id=data.question_id,
        bank_id=data.bank_id,
        user_answer=user_answer,
        is_correct=is_correct,
        time_spent=data.time_spent,
        mode=data.mode,
    )
    db.add(record)

    # 更新题目正确率（滑动平均）
    old_count = question.answer_count or 0
    old_rate = question.correct_rate or 0.0
    total = old_count + 1
    question.correct_rate = (old_rate * old_count + (1 if is_correct else 0)) / total
    question.answer_count = total

    # 更新用户进度
    progress = _get_or_create_progress(db, user_id, data.bank_id)
    progress.total_answered = (progress.total_answered or 0) + 1
    if is_correct:
        progress.correct_count = (progress.correct_count or 0) + 1

    db.commit()

    return AnswerResult(
        is_correct=is_correct,
        correct_answer=question.answer or "",
        explanation=question.explanation or "",
        correct_rate=round(question.correct_rate, 3),
    )


def toggle_star(db: Session, user_id: int, bank_id: int, question_id: int) -> bool:
    """收藏/取消收藏，返回当前状态（True=已收藏）"""
    question = db.query(Question).join(QuestionBank).filter(
        Question.id == question_id,
        Question.bank_id == bank_id,
        Question.status == "active",
        QuestionBank.status == BankStatus.ready,
    ).first()
    if not question:
        raise ValueError("题目不存在或不属于该题库")

    progress = _get_or_create_progress(db, user_id, bank_id)

    starred = list(progress.starred_ids or [])
    if question_id in starred:
        starred.remove(question_id)
        is_starred = False
    else:
        starred.append(question_id)
        is_starred = True

    progress.starred_ids = starred
    db.commit()
    return is_starred


def update_progress_position(db: Session, user_id: int, bank_id: int, position: int):
    bank = db.query(QuestionBank.id).filter(
        QuestionBank.id == bank_id,
        QuestionBank.status == BankStatus.ready,
    ).first()
    if not bank:
        raise ValueError("题库不存在")

    progress = _get_or_create_progress(db, user_id, bank_id)
    progress.last_position = position
    db.commit()


# ──────────────────────────────────────────
#  用户统计
# ──────────────────────────────────────────

def get_user_stats(db: Session, user_id: int) -> dict:
    total_records = db.query(AnswerRecord).filter(AnswerRecord.user_id == user_id).count()
    correct_records = db.query(AnswerRecord).filter(
        AnswerRecord.user_id == user_id,
        AnswerRecord.is_correct == True,
    ).count()
    wrong_count = len(get_current_wrong_question_ids(db, user_id))

    banks_studied = db.query(UserProgress).filter(
        UserProgress.user_id == user_id,
        UserProgress.total_answered > 0,
    ).count()

    # 今日作答
    today_start = datetime.combine(date.today(), datetime.min.time())
    today_answered = db.query(AnswerRecord).filter(
        AnswerRecord.user_id == user_id,
        AnswerRecord.answered_at >= today_start,
    ).count()

    # 收藏总数（合并所有题库）
    starred_count = 0
    all_progress = db.query(UserProgress).filter(UserProgress.user_id == user_id).all()
    for p in all_progress:
        starred_count += len(p.starred_ids or [])

    accuracy = round(correct_records / total_records, 3) if total_records > 0 else 0.0
    answered_days = {
        record.answered_at.date()
        for record in db.query(AnswerRecord.answered_at).filter(
            AnswerRecord.user_id == user_id,
            AnswerRecord.answered_at.isnot(None),
        ).all()
    }
    streak_days = 0
    cursor = date.today()
    while cursor in answered_days:
        streak_days += 1
        cursor -= timedelta(days=1)

    result = {
        "total_answered": total_records,
        "correct_count": correct_records,
        "accuracy": accuracy,
        "banks_studied": banks_studied,
        "wrong_count": wrong_count,
        "starred_count": starred_count,
        "today_answered": today_answered,
        "streak_days": streak_days,
    }
    return result


def recover_stale_tasks(db: Session, stale_minutes: int = 60) -> int:
    """Mark interrupted background tasks as failed after a process restart."""
    if stale_minutes <= 0:
        raise ValueError("stale_minutes must be positive")

    stale_before = datetime.utcnow() - timedelta(minutes=stale_minutes)
    tasks = db.query(GenerateTask).filter(
        GenerateTask.status.in_([TaskStatus.pending, TaskStatus.running]),
        sa_func.coalesce(GenerateTask.updated_at, GenerateTask.created_at) < stale_before,
    ).all()
    for task in tasks:
        task.status = TaskStatus.failed
        task.message = "任务因服务重启或超时已终止"
        task.error = f"stale task recovered after {stale_minutes} minutes"
        bank = db.query(QuestionBank).filter(QuestionBank.id == task.bank_id).first()
        if bank and bank.source_type != "url" and bank.source_file and os.path.isfile(bank.source_file):
            try:
                os.remove(bank.source_file)
            except OSError:
                logger.warning("无法清理过期任务源文件 %s", bank.source_file, exc_info=True)
    if tasks:
        db.commit()
    return len(tasks)


# ──────────────────────────────────────────
#  异步出题任务
# ──────────────────────────────────────────

async def run_generate_task(
    task_id: str,
    bank_id: int,
    file_path: str,
    source_type: str,
    db_factory,
    num_direct: int = 3,
    num_logic: int = 2,
):
    """
    后台异步出题任务主流程
    db_factory: 无参可调用，返回新的 DB Session
    """
    db: Session = db_factory()
    try:
        def ensure_bank_active() -> None:
            db.expire_all()
            status = db.query(QuestionBank.status).filter(
                QuestionBank.id == bank_id,
            ).scalar()
            if status is None or status in (BankStatus.deleted, BankStatus.deleted.value):
                raise GenerationCancelled("题库已删除")

        task = db.query(GenerateTask).filter(GenerateTask.id == task_id).first()
        if not task:
            return
        ensure_bank_active()

        task.status = TaskStatus.running
        task.message = "正在解析文档..."
        db.commit()

        # 1. 解析文档
        text = await parse_document(file_path, source_type)
        ensure_bank_active()
        if not text.strip():
            raise ValueError("文档内容为空，请检查文件")

        # 2. 分块
        chunks = split_text_into_chunks(text)
        task.total_chunks = len(chunks)
        task.message = f"文档已分为 {len(chunks)} 个段落，开始出题..."
        db.commit()

        # 3. 进度回调
        async def on_progress(processed: int, total: int, generated: int, msg: str):
            ensure_bank_active()
            t = db.query(GenerateTask).filter(GenerateTask.id == task_id).first()
            if t:
                t.processed_chunks = processed
                t.generated_count = generated
                t.progress = int(processed / total * 90)
                t.message = msg
                db.commit()

        # 4. AI 出题
        questions = await generate_questions_from_chunks(
            chunks=chunks,
            bank_id=bank_id,
            progress_callback=on_progress,
            num_direct=num_direct,
            num_logic=num_logic,
        )
        ensure_bank_active()

        # 5. 补全标签
        task.message = "正在整理知识点标签..."
        db.commit()
        questions = await classify_questions_tags(questions)
        ensure_bank_active()

        # 6. 批量写入数据库
        for i, q in enumerate(questions):
            q["order_index"] = i
            db.add(Question(**q))

        db.flush()
        updated = db.query(QuestionBank).filter(
            QuestionBank.id == bank_id,
        QuestionBank.status == BankStatus.ready,
        ).update(
            {
                QuestionBank.total_count: len(questions),
                QuestionBank.status: BankStatus.ready,
            },
            synchronize_session=False,
        )
        if updated != 1:
            raise GenerationCancelled("题库已删除")

        task.status = TaskStatus.done
        task.progress = 100
        task.generated_count = len(questions)
        task.message = f"出题完成！共生成 {len(questions)} 道题目"
        db.commit()

    except GenerationCancelled:
        db.rollback()
        task = db.query(GenerateTask).filter(GenerateTask.id == task_id).first()
        if task:
            task.status = TaskStatus.failed
            task.error = "bank deleted"
            task.message = "题库已删除，生成已停止"
            db.commit()
    except Exception as e:
        logger.error(f"出题任务 {task_id} 失败: {e}", exc_info=True)
        db.rollback()
        task = db.query(GenerateTask).filter(GenerateTask.id == task_id).first()
        if task:
            task.status = TaskStatus.failed
            task.error = str(e)
            task.message = "出题失败，请重试"
            db.commit()
    finally:
        db.close()
        if source_type != "url" and file_path and os.path.isfile(file_path):
            try:
                os.remove(file_path)
            except OSError:
                logger.warning("无法清理源文件 %s", file_path, exc_info=True)
