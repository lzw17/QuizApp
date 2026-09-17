"""
刷题 & 答题路由
POST /api/answer              提交单题答案
POST /api/exam/submit         模拟考试批量交卷
GET  /api/wrong-questions     获取错题列表
POST /api/star                收藏/取消收藏题目
POST /api/progress            更新顺序练习断点
GET  /api/progress/{bank_id}  获取用户在该题库的进度
GET  /api/stats               获取个人学习统计
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func as sa_func
from pydantic import BaseModel, Field

from ..database import get_db
from ..auth import get_current_user
from ..models.question import Question, QuestionBank, ExamSession, ExamSubmission
from ..models.user import AnswerRecord, User, UserProgress
from ..schemas.user import AnswerSubmit, AnswerResult, UserStatsOut, UserProgressOut
from ..schemas.question import QuestionPublicOut
from ..services.question_service import (
    submit_answer, toggle_star, update_progress_position,
    get_wrong_questions, get_user_stats,
    evaluate_answer, get_review_questions,
)
from ..services.bank_access import apply_bank_access, get_accessible_bank
from ..utils.time import local_day_utc_bounds, local_today, utc_now, utc_timestamp_to_local_date

router = APIRouter(prefix="/api", tags=["practice"])


# ──────────────────────────────────────────
#  答题
# ──────────────────────────────────────────

@router.post("/answer", response_model=AnswerResult)
def answer_question(
    data: AnswerSubmit,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """提交单题答案，返回是否正确 + 解析"""
    try:
        return submit_answer(db, data, current_user)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ──────────────────────────────────────────
#  模拟考试批量交卷
# ──────────────────────────────────────────

class ExamAnswerItem(BaseModel):
    question_id: int
    user_answer: str = Field(default="", max_length=20)
    time_spent: int = Field(default=0, ge=0, le=86400)


class ExamSubmitRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    bank_id: int
    answers: List[ExamAnswerItem] = Field(min_length=1, max_length=100)
    total_time: int = Field(default=0, ge=0, le=86400)  # 总用时（秒）


class ExamStartRequest(BaseModel):
    bank_id: int
    question_count: int = Field(default=20, ge=1, le=100)
    tag: Optional[str] = Field(default=None, max_length=100)
    difficulty: Optional[int] = Field(default=None, ge=1, le=5)


class ExamStartResult(BaseModel):
    session_id: str
    bank_id: int
    expires_at: datetime
    duration_seconds: int
    questions: List[QuestionPublicOut]


class ExamResultItem(BaseModel):
    question_id: int
    type: str
    content: str
    is_correct: bool
    correct_answer: str
    user_answer: str
    explanation: str


class ExamSubmitResult(BaseModel):
    total: int
    correct: int
    wrong: int
    score: float
    passed: bool
    results: List[ExamResultItem]


@router.post("/exam/submit", response_model=ExamSubmitResult)
def submit_exam(
    data: ExamSubmitRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """校验服务端考试实例后批量交卷判分。"""
    get_accessible_bank(db, data.bank_id, current_user)
    session_query = db.query(ExamSession).filter(
        ExamSession.id == data.session_id,
        ExamSession.user_id == current_user.id,
        ExamSession.bank_id == data.bank_id,
    )
    if db.bind and db.bind.dialect.name != "sqlite":
        session_query = session_query.with_for_update()
    session = session_query.first()
    if not session:
        raise HTTPException(400, "考试实例不存在或不属于当前用户")
    if session.submitted_at:
        submission = db.get(ExamSubmission, session.id)
        if submission:
            return ExamSubmitResult.model_validate(submission.result)
        raise HTTPException(409, "该考试已经提交，历史成绩暂不可恢复")
    if session.expires_at < utc_now():
        raise HTTPException(400, "考试已超时，请重新开始")

    expected_ids = [int(item) for item in (session.question_ids or [])]
    received_ids = [item.question_id for item in data.answers]
    if len(received_ids) != len(expected_ids) or len(set(received_ids)) != len(received_ids):
        raise HTTPException(400, "必须提交本次考试的全部题目且不能重复")
    if set(received_ids) != set(expected_ids):
        raise HTTPException(400, "提交的题目不属于本次考试")

    questions = db.query(Question).filter(
        Question.id.in_(expected_ids),
        Question.bank_id == data.bank_id,
        Question.status == "active",
    ).all()
    by_id = {question.id: question for question in questions}
    if len(by_id) != len(expected_ids):
        raise HTTPException(400, "考试题目已失效，请重新开始")
    # 先完整校验答案，避免部分写入后才发现非法答案。
    normalized_answers = {}
    for item in data.answers:
        try:
            normalized_answers[item.question_id] = evaluate_answer(
                by_id[item.question_id],
                item.user_answer,
                allow_empty=True,
            )[0]
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    claimed_at = utc_now()
    claimed = db.query(ExamSession).filter(
        ExamSession.id == session.id,
        ExamSession.submitted_at.is_(None),
    ).update(
        {ExamSession.submitted_at: claimed_at},
        synchronize_session=False,
    )
    if claimed != 1:
        db.rollback()
        submission = db.get(ExamSubmission, session.id)
        if submission:
            return ExamSubmitResult.model_validate(submission.result)
        raise HTTPException(409, "该考试已经提交")

    results = []
    correct_count = 0

    for item in data.answers:
        submit = AnswerSubmit(
            question_id=item.question_id,
            bank_id=data.bank_id,
            user_answer=normalized_answers[item.question_id],
            time_spent=item.time_spent,
            mode="exam",
        )
        try:
            result = submit_answer(db, submit, current_user, commit=False)
            question = db.query(Question).filter(Question.id == item.question_id).first()
            results.append(ExamResultItem(
                question_id=item.question_id,
                type=question.type if question else "single",
                content=question.content if question else "",
                is_correct=result.is_correct,
                correct_answer=result.correct_answer,
                user_answer=normalized_answers[item.question_id],
                explanation=result.explanation,
            ))
            if result.is_correct:
                correct_count += 1
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    total = len(results)
    score = round(correct_count / total * 100, 1) if total > 0 else 0.0
    submission_result = ExamSubmitResult(
        total=total,
        correct=correct_count,
        wrong=total - correct_count,
        score=score,
        passed=score >= 60.0,
        results=results,
    )
    db.add(ExamSubmission(
        session_id=session.id,
        user_id=current_user.id,
        bank_id=data.bank_id,
        result=submission_result.model_dump(mode="json"),
    ))
    db.commit()
    return submission_result


@router.post("/exam/start", response_model=ExamStartResult)
def start_exam(
    data: ExamStartRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建服务端考试实例并返回不含答案的题目。"""
    bank = get_accessible_bank(db, data.bank_id, current_user)
    questions = db.query(Question).filter(
        Question.bank_id == data.bank_id,
        Question.status == "active",
    )
    if data.tag:
        questions = questions.filter(
            Question.tags.contains(f'"{data.tag}"', autoescape=True)
        )
    if data.difficulty:
        questions = questions.filter(Question.difficulty == data.difficulty)
    questions = questions.order_by(sa_func.random()).limit(data.question_count).all()
    if not questions:
        raise HTTPException(400, "题库暂无可用题目")
    session_id = uuid.uuid4().hex
    duration_seconds = max(10 * 60, len(questions) * 90)
    # Keep a short server-side grace period for the final request in flight.
    expires_at = utc_now() + timedelta(seconds=duration_seconds + 30)
    session = ExamSession(
        id=session_id,
        user_id=current_user.id,
        bank_id=data.bank_id,
        question_ids=[question.id for question in questions],
        expires_at=expires_at,
    )
    db.add(session)
    db.commit()
    return ExamStartResult(
        session_id=session_id,
        bank_id=data.bank_id,
        expires_at=expires_at.replace(tzinfo=timezone.utc),
        duration_seconds=duration_seconds,
        questions=questions,
    )


# ──────────────────────────────────────────
#  错题本
# ──────────────────────────────────────────

@router.get("/wrong-questions")
def list_wrong_questions(
    bank_id: Optional[int] = Query(None, ge=1),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取用户错题列表（每题只显示最近一次答错）"""
    return get_wrong_questions(db, current_user, bank_id, skip=skip, limit=limit)


@router.get("/starred-questions")
def list_starred_questions(
    bank_id: Optional[int] = Query(None, ge=1),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """只返回当前用户已收藏题目的复习数据（包含答案和解析）。"""
    if bank_id is not None:
        get_accessible_bank(db, bank_id, current_user)
    return get_review_questions(
        db, current_user, bank_id, "starred", skip=skip, limit=limit
    )


# ──────────────────────────────────────────
#  收藏
# ──────────────────────────────────────────

@router.get("/review-questions")
def list_review_questions(
    bank_id: Optional[int] = Query(None, ge=1),
    source: str = Query("wrong", pattern="^(wrong|starred)$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    after_id: Optional[int] = Query(None, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return answer-bearing questions only for a user's own review set."""
    if bank_id is not None:
        get_accessible_bank(db, bank_id, current_user)
    try:
        return get_review_questions(
            db,
            current_user,
            bank_id,
            source,
            skip=skip,
            limit=limit,
            after_id=after_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/daily-question")
def get_daily_question(
    bank_id: Optional[int] = Query(None, ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pick a deterministic question for the current day and bank."""
    bank_query = apply_bank_access(db.query(QuestionBank), current_user)
    if bank_id:
        bank_query = bank_query.filter(QuestionBank.id == bank_id)
    bank = bank_query.order_by(QuestionBank.id.desc()).first()
    if not bank:
        raise HTTPException(404, "no ready question bank")
    questions = db.query(Question).filter(
        Question.bank_id == bank.id,
        Question.status == "active",
    ).order_by(Question.order_index, Question.id).all()
    if not questions:
        raise HTTPException(404, "question bank is empty")
    today = local_today()
    question = questions[int(today.strftime("%Y%m%d")) % len(questions)]
    today_start, today_end = local_day_utc_bounds(today)
    answered = db.query(AnswerRecord.id).filter(
        AnswerRecord.user_id == current_user.id,
        AnswerRecord.question_id == question.id,
        AnswerRecord.answered_at >= today_start,
        AnswerRecord.answered_at <= today_end,
    ).first() is not None
    return {
        "date": today.isoformat(),
        "bank_id": bank.id,
        "bank_name": bank.name,
        "is_answered": answered,
        "question": QuestionPublicOut.model_validate(question).model_dump(),
    }


@router.get("/study-report")
def get_study_report(
    days: int = Query(7, ge=7, le=30),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return daily activity, accuracy trend and weak knowledge tags."""
    today = local_today()
    start_date = today - timedelta(days=days - 1)
    start_at, _ = local_day_utc_bounds(start_date)
    records = db.query(AnswerRecord).filter(
        AnswerRecord.user_id == current_user.id,
        AnswerRecord.answered_at >= start_at,
    ).all()
    daily = {
        current_date: {"date": current_date.isoformat(), "total": 0, "correct": 0}
        for current_date in (start_date + timedelta(days=i) for i in range(days))
    }
    question_ids = {record.question_id for record in records}
    questions = db.query(Question).filter(Question.id.in_(question_ids)).all() if question_ids else []
    by_id = {question.id: question for question in questions}
    weak_tags = {}
    for record in records:
        current_date = utc_timestamp_to_local_date(record.answered_at or utc_now())
        if current_date not in daily:
            continue
        daily[current_date]["total"] += 1
        if record.is_correct:
            daily[current_date]["correct"] += 1
        else:
            question = by_id.get(record.question_id)
            for tag in (question.tags or []) if question else []:
                weak_tags[str(tag)] = weak_tags.get(str(tag), 0) + 1
    daily_result = []
    for item in daily.values():
        item["accuracy"] = round(item["correct"] / item["total"], 3) if item["total"] else 0.0
        daily_result.append(item)
    weak_result = [
        {"tag": tag, "count": count}
        for tag, count in sorted(weak_tags.items(), key=lambda pair: (-pair[1], pair[0]))[:3]
    ]
    return {
        "days": days,
        "daily": daily_result,
        "weak_tags": weak_result,
        "active_days": sum(1 for item in daily_result if item["total"]),
        "streak_days": get_user_stats(db, current_user.id)["streak_days"],
    }


class StarRequest(BaseModel):
    bank_id: int
    question_id: int


@router.post("/star")
def star_question(
    data: StarRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        is_starred = toggle_star(db, current_user, data.bank_id, data.question_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"is_starred": is_starred, "question_id": data.question_id}


# ──────────────────────────────────────────
#  练习进度
# ──────────────────────────────────────────

class ProgressUpdateRequest(BaseModel):
    bank_id: int
    position: int = Field(ge=0)
    reset: bool = False


@router.post("/progress")
def update_progress(
    data: ProgressUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if data.position < 0:
        raise HTTPException(400, "进度位置不能为负数")
    try:
        update_progress_position(
            db,
            current_user,
            data.bank_id,
            data.position,
            reset=data.reset,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"message": "进度已保存"}


@router.get("/progress/{bank_id}", response_model=UserProgressOut)
def get_progress(
    bank_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_accessible_bank(db, bank_id, current_user)

    progress = db.query(UserProgress).filter(
        UserProgress.user_id == current_user.id,
        UserProgress.bank_id == bank_id,
    ).first()
    if not progress:
        return UserProgressOut(
            bank_id=bank_id,
            last_position=0,
            total_answered=0,
            correct_count=0,
            accuracy=0.0,
            starred_ids=[],
        )
    accuracy = (
        round(progress.correct_count / progress.total_answered, 3)
        if progress.total_answered > 0 else 0.0
    )
    return UserProgressOut(
        bank_id=bank_id,
        last_position=progress.last_position,
        total_answered=progress.total_answered,
        correct_count=progress.correct_count,
        accuracy=accuracy,
        starred_ids=progress.starred_ids or [],
    )


# ──────────────────────────────────────────
#  学习统计
# ──────────────────────────────────────────

@router.get("/stats", response_model=UserStatsOut)
def get_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_user_stats(db, current_user.id)
