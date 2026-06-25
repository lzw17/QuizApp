from sqlalchemy import Column, Integer, String, Text, Float, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    openid = Column(String(100), unique=True, index=True, nullable=False, comment="微信 openid")
    nickname = Column(String(100), default="", comment="昵称")
    avatar = Column(String(500), default="", comment="头像 URL")
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    last_login = Column(DateTime, server_default=func.now(), onupdate=func.now())

    progress_list = relationship("UserProgress", back_populates="user")
    answer_records = relationship("AnswerRecord", back_populates="user")


class UserProgress(Base):
    """用户在某题库的练习进度"""
    __tablename__ = "user_progress"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    bank_id = Column(Integer, ForeignKey("question_banks.id"), nullable=False, index=True)
    last_position = Column(Integer, default=0, comment="顺序练习断点位置（题目 order_index）")
    total_answered = Column(Integer, default=0, comment="累计作答题数")
    correct_count = Column(Integer, default=0, comment="答对题数")
    starred_ids = Column(JSON, default=list, comment="收藏的题目 id 列表")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="progress_list")


class AnswerRecord(Base):
    """每次答题记录"""
    __tablename__ = "answer_records"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False, index=True)
    bank_id = Column(Integer, nullable=False, index=True)
    user_answer = Column(String(20), default="", comment="用户选择的答案")
    is_correct = Column(Boolean, nullable=False)
    time_spent = Column(Integer, default=0, comment="作答耗时（秒）")
    mode = Column(String(20), default="practice", comment="practice/exam/review")
    answered_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="answer_records")
