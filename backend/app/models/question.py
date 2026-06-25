from sqlalchemy import Column, Integer, String, Text, Float, Boolean, DateTime, JSON, ForeignKey, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..database import Base
import enum


class QuestionType(str, enum.Enum):
    single = "single"   # 单选题
    multi = "multi"     # 多选题
    judge = "judge"     # 判断题


class BankStatus(str, enum.Enum):
    pending = "pending"     # 生成中
    ready = "ready"         # 可用
    reviewing = "reviewing" # 审核中


class TaskStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class QuestionBank(Base):
    __tablename__ = "question_banks"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, comment="题库名称")
    description = Column(Text, default="", comment="题库描述")
    cover = Column(String(500), default="", comment="封面图 URL")
    category = Column(String(100), default="", comment="分类标签")
    total_count = Column(Integer, default=0, comment="题目总数")
    status = Column(String(20), default=BankStatus.pending, comment="状态")
    source_file = Column(String(500), default="", comment="原始文档路径/URL")
    source_type = Column(String(20), default="", comment="pdf/word/url")
    created_by = Column(String(100), default="", comment="创建者 openid")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    questions = relationship("Question", back_populates="bank", cascade="all, delete-orphan")


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True)
    bank_id = Column(Integer, ForeignKey("question_banks.id"), nullable=False, index=True)
    type = Column(String(10), nullable=False, comment="single/multi/judge")
    content = Column(Text, nullable=False, comment="题干")
    options = Column(JSON, default=list, comment='[{"key":"A","text":"..."}]')
    answer = Column(String(20), nullable=False, comment="正确答案，如 A 或 AB")
    explanation = Column(Text, default="", comment="解析说明")
    tags = Column(JSON, default=list, comment="知识点标签列表")
    difficulty = Column(Integer, default=3, comment="难度 1-5")
    correct_rate = Column(Float, default=0.0, comment="历史正确率 0-1")
    answer_count = Column(Integer, default=0, comment="被作答次数")
    status = Column(String(20), default="active", comment="active/deleted")
    order_index = Column(Integer, default=0, comment="在题库中的顺序")
    created_at = Column(DateTime, server_default=func.now())

    bank = relationship("QuestionBank", back_populates="questions")


class GenerateTask(Base):
    """AI 出题异步任务追踪"""
    __tablename__ = "generate_tasks"

    id = Column(String(64), primary_key=True, comment="UUID")
    bank_id = Column(Integer, ForeignKey("question_banks.id"), nullable=True)
    status = Column(String(20), default=TaskStatus.pending)
    progress = Column(Integer, default=0, comment="进度 0-100")
    total_chunks = Column(Integer, default=0, comment="总分块数")
    processed_chunks = Column(Integer, default=0, comment="已处理分块数")
    generated_count = Column(Integer, default=0, comment="已生成题目数")
    message = Column(String(500), default="", comment="当前状态描述")
    error = Column(Text, default="", comment="错误信息")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
