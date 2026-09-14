from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class UserOut(BaseModel):
    id: int
    nickname: Optional[str] = ""
    avatar: Optional[str] = ""
    is_admin: bool

    class Config:
        from_attributes = True


class AnswerSubmit(BaseModel):
    question_id: int
    bank_id: int
    user_answer: str = Field(default="", max_length=20)
    time_spent: int = Field(default=0, ge=0, le=86400)
    mode: str = Field(default="practice", max_length=20)


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
