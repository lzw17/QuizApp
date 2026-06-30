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
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session
from pydantic import BaseModel

from ..database import get_db
from ..models.question import Question
from ..models.user import UserProgress
from ..schemas.user import AnswerSubmit, AnswerResult, UserStatsOut, UserProgressOut
from ..services.question_service import (
    submit_answer, toggle_star, update_progress_position,
    get_wrong_questions, get_user_stats,
)

router = APIRouter(prefix="/api", tags=["practice"])


# ──────────────────────────────────────────
#  答题
# ──────────────────────────────────────────

@router.post("/answer", response_model=AnswerResult)
def answer_question(data: AnswerSubmit, db: Session = Depends(get_db)):
    """提交单题答案，返回是否正确 + 解析"""
    try:
        return submit_answer(db, data)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ──────────────────────────────────────────
#  模拟考试批量交卷
# ──────────────────────────────────────────

class ExamAnswerItem(BaseModel):
    question_id: int
    user_answer: str
    time_spent: int = 0


class ExamSubmitRequest(BaseModel):
    user_id: int
    bank_id: int
    answers: List[ExamAnswerItem]
    total_time: int = 0  # 总用时（秒）


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
def submit_exam(data: ExamSubmitRequest, db: Session = Depends(get_db)):
    """模拟考试批量交卷判分"""
    results = []
    correct_count = 0

    for item in data.answers:
        submit = AnswerSubmit(
            user_id=data.user_id,
            question_id=item.question_id,
            bank_id=data.bank_id,
            user_answer=item.user_answer,
            time_spent=item.time_spent,
            mode="exam",
        )
        try:
            result = submit_answer(db, submit)
            question = db.query(Question).filter(Question.id == item.question_id).first()
            results.append(ExamResultItem(
                question_id=item.question_id,
                type=question.type if question else "single",
                content=question.content if question else "",
                is_correct=result.is_correct,
                correct_answer=result.correct_answer,
                user_answer=item.user_answer,
                explanation=result.explanation,
            ))
            if result.is_correct:
                correct_count += 1
        except ValueError:
            continue

    total = len(results)
    score = round(correct_count / total * 100, 1) if total > 0 else 0.0

    return ExamSubmitResult(
        total=total,
        correct=correct_count,
        wrong=total - correct_count,
        score=score,
        passed=score >= 60.0,
        results=results,
    )


# ──────────────────────────────────────────
#  错题本
# ──────────────────────────────────────────

@router.get("/wrong-questions")
def list_wrong_questions(
    user_id: int = Query(...),
    bank_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """获取用户错题列表（每题只显示最近一次答错）"""
    return get_wrong_questions(db, user_id, bank_id)


# ──────────────────────────────────────────
#  收藏
# ──────────────────────────────────────────

class StarRequest(BaseModel):
    user_id: int
    bank_id: int
    question_id: int


@router.post("/star")
def star_question(data: StarRequest, db: Session = Depends(get_db)):
    is_starred = toggle_star(db, data.user_id, data.bank_id, data.question_id)
    return {"is_starred": is_starred, "question_id": data.question_id}


# ──────────────────────────────────────────
#  练习进度
# ──────────────────────────────────────────

class ProgressUpdateRequest(BaseModel):
    user_id: int
    bank_id: int
    position: int


@router.post("/progress")
def update_progress(data: ProgressUpdateRequest, db: Session = Depends(get_db)):
    update_progress_position(db, data.user_id, data.bank_id, data.position)
    return {"message": "进度已保存"}


@router.get("/progress/{bank_id}", response_model=UserProgressOut)
def get_progress(
    bank_id: int,
    user_id: int = Query(...),
    db: Session = Depends(get_db),
):
    progress = db.query(UserProgress).filter(
        UserProgress.user_id == user_id,
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
def get_stats(user_id: int = Query(...), db: Session = Depends(get_db)):
    return get_user_stats(db, user_id)
