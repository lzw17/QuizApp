from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class UserOut(BaseModel):
    id: int
    openid: str
    nickname: str
    avatar: str
    is_admin: bool

    class Config:
        from_attributes = True


class AnswerSubmit(BaseModel):
    user_id: int
    question_id: int
    bank_id: int
    user_answer: str
    time_spent: int = 0
    mode: str = "practice"


class AnswerResult(BaseModel):
    is_correct: bool
    correct_answer: str
    explanation: str
    correct_rate: float


class WrongQuestionOut(BaseModel):
    id: int
    question_id: int
    bank_id: int
    user_answer: str
    answered_at: datetime
    question: dict

    class Config:
        from_attributes = True


class UserStatsOut(BaseModel):
    total_answered: int
    correct_count: int
    accuracy: float
    banks_studied: int
    wrong_count: int
    starred_count: int
    today_answered: int
    streak_days: int


class UserProgressOut(BaseModel):
    bank_id: int
    last_position: int
    total_answered: int
    correct_count: int
    accuracy: float
    starred_ids: List[int]

    class Config:
        from_attributes = True
