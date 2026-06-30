from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime


class OptionItem(BaseModel):
    key: str        # A / B / C / D
    text: str       # 选项文字


class QuestionBankCreate(BaseModel):
    name: str
    description: str = ""
    category: str = ""


class QuestionBankListItem(BaseModel):
    id: int
    name: str
    description: str
    cover: str
    category: str
    total_count: int
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class QuestionBankOut(QuestionBankListItem):
    source_type: str
    tags: List[str] = []


class QuestionCreate(BaseModel):
    bank_id: int
    type: str  # single / multi / judge
    content: str
    options: List[OptionItem] = []
    answer: str
    explanation: str = ""
    tags: List[str] = []
    difficulty: int = Field(default=3, ge=1, le=5)


class QuestionOut(BaseModel):
    id: int
    bank_id: int
    type: str
    content: str
    options: List[Any]
    answer: str
    explanation: str
    tags: List[Any]
    difficulty: int
    correct_rate: float
    order_index: int

    class Config:
        from_attributes = True


class GenerateTaskOut(BaseModel):
    id: str
    bank_id: Optional[int] = None
    status: str = "pending"
    progress: int = 0
    total_chunks: int = 0
    processed_chunks: int = 0
    generated_count: int = 0
    message: str = ""
    error: str = ""

    class Config:
        from_attributes = True


class UploadResponse(BaseModel):
    task_id: str
    bank_id: int
    message: str
