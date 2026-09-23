from pydantic import BaseModel, Field, model_validator
from typing import Optional, List, Any, Literal
from datetime import datetime


class OptionItem(BaseModel):
    key: str = Field(min_length=1, max_length=1)
    text: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def normalize(self):
        self.key = self.key.strip().upper()
        self.text = self.text.strip()
        if not self.key or not self.text:
            raise ValueError("option key and text must not be empty")
        return self


class QuestionBankCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    category: str = Field(default="", max_length=100)

    @model_validator(mode="after")
    def normalize(self):
        self.name = self.name.strip()
        self.description = self.description.strip()
        self.category = self.category.strip()
        if not self.name:
            raise ValueError("bank name must not be empty")
        return self


class QuestionBankListItem(BaseModel):
    id: int
    name: str
    description: str
    cover: str
    category: str
    total_count: int
    status: str
    created_at: datetime
    can_delete: bool = False

    class Config:
        from_attributes = True


class QuestionBankOut(QuestionBankListItem):
    source_type: str
    tags: List[str] = []


class QuestionCreate(BaseModel):
    bank_id: int
    type: Literal["single", "multi", "judge"]
    content: str = Field(min_length=1, max_length=10000)
    options: List[OptionItem] = Field(default_factory=list)
    answer: str = Field(min_length=1, max_length=20)
    explanation: str = Field(default="", max_length=20000)
    tags: List[str] = Field(default_factory=list)
    difficulty: int = Field(default=3, ge=1, le=5)

    @model_validator(mode="after")
    def validate_answer(self):
        self.content = self.content.strip()
        self.answer = "".join(self.answer.split()).upper()
        self.explanation = self.explanation.strip()

        if self.type == "judge" and not self.options:
            self.options = [
                OptionItem(key="A", text="正确"),
                OptionItem(key="B", text="错误"),
            ]
        if not self.content or not self.options:
            raise ValueError("content and options must not be empty")

        keys = [option.key for option in self.options]
        if len(keys) != len(set(keys)):
            raise ValueError("option keys must be unique")
        answer_keys = list(self.answer)
        if not answer_keys or any(key not in keys for key in answer_keys):
            raise ValueError("answer must reference available option keys")
        if self.type in ("single", "judge") and len(answer_keys) != 1:
            raise ValueError(f"{self.type} questions require exactly one answer")
        if self.type == "multi" and len(answer_keys) < 1:
            raise ValueError("multi questions require at least one answer")
        if len(set(answer_keys)) != len(answer_keys):
            raise ValueError("answer keys must be unique")
        return self


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


class QuestionPublicOut(BaseModel):
    """题库、练习和考试开始接口使用的公开题目模型，不包含标准答案。"""
    id: int
    bank_id: int
    type: str
    content: str
    options: List[Any]
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
    failed_chunks: int = 0
    generated_count: int = 0
    partial_success: bool = False
    message: str = ""
    error: str = ""

    class Config:
        from_attributes = True


class UploadResponse(BaseModel):
    task_id: str
    bank_id: int
    message: str
