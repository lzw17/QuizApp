"""
题库和答题业务逻辑
"""
from datetime import datetime, timedelta
from typing import List, Optional
from sqlalchemy.orm import Session, aliased
from sqlalchemy import and_, or_, func as sa_func
from sqlalchemy.exc import IntegrityError

from ..models.question import Question, QuestionBank
from ..models.user import User, UserProgress, AnswerRecord
from ..schemas.user import AnswerSubmit, AnswerResult
from ..services.bank_access import apply_bank_access
from ..utils.time import local_day_utc_bounds, local_today, utc_now, utc_timestamp_to_local_date


def evaluate_answer(
    question: Question,
    raw_answer: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, bool]:
    """Normalize and validate one answer without writing any database records."""
    allowed_keys = {str(item.get("key", "")).strip().upper() for item in (question.options or [])}
    correct_answer = "".join(str(question.answer or "").split()).upper()
    user_answer = "".join(str(raw_answer or "").split()).upper()
    if not allowed_keys or not correct_answer:
        raise ValueError("题目选项或标准答案无效")
    # An unanswered exam question is a valid submission and is simply wrong.
    # Interactive practice still rejects empty answers so accidental taps do not
    # create answer records.
    if not user_answer and allow_empty:
        return "", False
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


def get_wrong_questions(
    db: Session,
    user: User,
    bank_id: Optional[int] = None,
    *,
    skip: int = 0,
    limit: int = 50,
) -> List[dict]:
    """获取用户错题，每道题只取最近一次错误记录"""
    latest = get_latest_answer_records(db, user.id, bank_id)
    unique = [record for record in latest.values() if not record.is_correct]
    unique.sort(key=lambda record: record.answered_at or datetime.min, reverse=True)

    question_ids = [record.question_id for record in unique]
    questions = []
    if question_ids:
        query = db.query(Question).join(QuestionBank).filter(
            Question.id.in_(question_ids),
            Question.status == "active",
        )
        questions = apply_bank_access(query, user).all()
    by_id = {question.id: question for question in questions}
    visible = [record for record in unique if record.question_id in by_id]

    results = []
    for record in visible[skip:skip + limit]:
        q = by_id[record.question_id]
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
    """Return only the latest attempt per question using a correlated query.

    The previous implementation loaded every historical attempt into Python,
    which becomes increasingly expensive for active users.  The database can
    discard older attempts before the rows reach the application instead.
    """
    newer = aliased(AnswerRecord)
    query = db.query(AnswerRecord).filter(AnswerRecord.user_id == user_id)
    if bank_id:
        query = query.filter(AnswerRecord.bank_id == bank_id)

    newer_attempt = db.query(newer.id).filter(
        newer.user_id == AnswerRecord.user_id,
        newer.question_id == AnswerRecord.question_id,
        or_(
            newer.answered_at > AnswerRecord.answered_at,
            and_(
                newer.answered_at == AnswerRecord.answered_at,
                newer.id > AnswerRecord.id,
            ),
        ),
    )
    if bank_id:
        newer_attempt = newer_attempt.filter(newer.bank_id == bank_id)
    query = query.filter(~newer_attempt.exists()).order_by(
        AnswerRecord.answered_at.desc(),
        AnswerRecord.id.desc(),
    )
    return {record.question_id: record for record in query.all()}


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


def get_starred_question_ids(
    db: Session,
    user_id: int,
    bank_id: Optional[int] = None,
) -> List[int]:
    """Return the user's starred question ids across one or all banks."""
    query = db.query(UserProgress).filter(UserProgress.user_id == user_id)
    if bank_id is not None:
        query = query.filter(UserProgress.bank_id == bank_id)
    result = []
    seen = set()
    for progress in query.order_by(UserProgress.id).all():
        for question_id in progress.starred_ids or []:
            if question_id not in seen:
                seen.add(question_id)
                result.append(question_id)
    return result


def get_review_questions(
    db: Session,
    user: User,
    bank_id: Optional[int],
    source: str,
    *,
    skip: int = 0,
    limit: int = 100,
    after_id: Optional[int] = None,
) -> List[dict]:
    """Return answer-bearing questions only for the user's review set."""
    if source == "wrong":
        question_ids = get_current_wrong_question_ids(db, user.id, bank_id)
    elif source == "starred":
        question_ids = get_starred_question_ids(db, user.id, bank_id)
    else:
        raise ValueError("source must be wrong or starred")

    if not question_ids:
        return []
    query = db.query(Question).join(QuestionBank).filter(
        Question.id.in_(question_ids),
        Question.status == "active",
    )
    query = apply_bank_access(query, user)
    if bank_id is not None:
        query = query.filter(Question.bank_id == bank_id)
    if after_id is not None:
        query = query.filter(Question.id > after_id)
        skip = 0
    questions = query.order_by(Question.id).offset(skip).limit(limit).all()
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
        for question in questions
    ]


# ──────────────────────────────────────────
#  答题逻辑
# ──────────────────────────────────────────

def submit_answer(
    db: Session,
    data: AnswerSubmit,
    user: User,
    *,
    commit: bool = True,
) -> AnswerResult:
    """Record one answer, optionally leaving the transaction open for a batch."""
    query = db.query(Question).join(QuestionBank).filter(
        Question.id == data.question_id,
        Question.bank_id == data.bank_id,
        Question.status == "active",
    )
    question = apply_bank_access(query, user).first()
    if not question:
        raise ValueError("题目不存在或不属于该题库")

    user_answer, is_correct = evaluate_answer(
        question,
        data.user_answer,
        allow_empty=data.mode == "exam",
    )

    # 写入答题记录
    record = AnswerRecord(
        user_id=user.id,
        question_id=data.question_id,
        bank_id=data.bank_id,
        user_answer=user_answer,
        is_correct=is_correct,
        time_spent=data.time_spent,
        mode=data.mode,
        answered_at=utc_now(),
    )
    db.add(record)

    # Update aggregates atomically so concurrent answers cannot overwrite each
    # other's counters.
    old_count = sa_func.coalesce(Question.answer_count, 0)
    old_rate = sa_func.coalesce(Question.correct_rate, 0.0)
    db.query(Question).filter(Question.id == question.id).update(
        {
            Question.correct_rate: (old_rate * old_count + int(is_correct)) / (old_count + 1),
            Question.answer_count: old_count + 1,
        },
        synchronize_session=False,
    )
    db.refresh(question)

    # 更新用户进度
    progress = _get_or_create_progress(db, user.id, data.bank_id)
    db.query(UserProgress).filter(UserProgress.id == progress.id).update(
        {
            UserProgress.total_answered: sa_func.coalesce(UserProgress.total_answered, 0) + 1,
            UserProgress.correct_count: sa_func.coalesce(UserProgress.correct_count, 0) + int(is_correct),
        },
        synchronize_session=False,
    )
    db.refresh(progress)

    if commit:
        db.commit()

    return AnswerResult(
        is_correct=is_correct,
        correct_answer=question.answer or "",
        explanation=question.explanation or "",
        correct_rate=round(question.correct_rate, 3),
    )


def toggle_star(db: Session, user: User, bank_id: int, question_id: int) -> bool:
    """收藏/取消收藏，返回当前状态（True=已收藏）"""
    query = db.query(Question).join(QuestionBank).filter(
        Question.id == question_id,
        Question.bank_id == bank_id,
        Question.status == "active",
    )
    question = apply_bank_access(query, user).first()
    if not question:
        raise ValueError("题目不存在或不属于该题库")

    progress = _get_or_create_progress(db, user.id, bank_id)

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


def update_progress_position(
    db: Session,
    user: User,
    bank_id: int,
    position: int,
    *,
    reset: bool = False,
):
    query = db.query(QuestionBank.id).filter(QuestionBank.id == bank_id)
    bank = apply_bank_access(query, user).first()
    if not bank:
        raise ValueError("题库不存在")

    progress = _get_or_create_progress(db, user.id, bank_id)
    progress.last_position = position if reset else max(progress.last_position or 0, position)
    db.commit()


# ──────────────────────────────────────────
#  用户统计
# ──────────────────────────────────────────

def get_user_stats(db: Session, user_id: int) -> dict:
    user = db.get(User, user_id)
    total_records = db.query(AnswerRecord).filter(AnswerRecord.user_id == user_id).count()
    correct_records = db.query(AnswerRecord).filter(
        AnswerRecord.user_id == user_id,
        AnswerRecord.is_correct == True,
    ).count()
    wrong_ids = get_current_wrong_question_ids(db, user_id)

    banks_studied = db.query(UserProgress).filter(
        UserProgress.user_id == user_id,
        UserProgress.total_answered > 0,
    ).count()

    # 今日作答
    today_start, today_end = local_day_utc_bounds()
    today_answered = db.query(AnswerRecord).filter(
        AnswerRecord.user_id == user_id,
        AnswerRecord.answered_at >= today_start,
        AnswerRecord.answered_at <= today_end,
    ).count()

    # 错题和收藏只统计当前仍可访问的有效题目，避免已删除题库继续
    # 出现在个人统计中，但在错题本列表里不可见。
    starred_ids = set()
    all_progress = db.query(UserProgress).filter(UserProgress.user_id == user_id).all()
    for p in all_progress:
        starred_ids.update(p.starred_ids or [])

    def count_accessible(question_ids) -> int:
        if not user or not question_ids:
            return 0
        query = db.query(sa_func.count(Question.id)).join(QuestionBank).filter(
            Question.id.in_(question_ids),
            Question.status == "active",
        )
        return int(apply_bank_access(query, user).scalar() or 0)

    wrong_count = count_accessible(wrong_ids)
    starred_count = count_accessible(starred_ids)

    accuracy = round(correct_records / total_records, 3) if total_records > 0 else 0.0
    answered_days = {
        utc_timestamp_to_local_date(record.answered_at)
        for record in db.query(AnswerRecord.answered_at).filter(
            AnswerRecord.user_id == user_id,
            AnswerRecord.answered_at.isnot(None),
        ).all()
    }
    streak_days = 0
    cursor = local_today()
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


def recover_interrupted_tasks(db: Session) -> List[str]:
    """Compatibility export for the durable generation service."""
    from .generation_service import recover_interrupted_tasks as recover

    return recover(db)
async def run_generate_task(task_id: str, db_factory, **_legacy_arguments):
    """Compatibility export for callers and existing integrations."""
    from .generation_service import run_generate_task as run

    await run(task_id=task_id, db_factory=db_factory)
