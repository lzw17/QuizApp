"""
题库和答题业务逻辑
"""
import uuid
import asyncio
import logging
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, func as sa_func

from ..models.question import QuestionBank, Question, GenerateTask, TaskStatus, BankStatus
from ..models.user import User, UserProgress, AnswerRecord
from ..schemas.question import QuestionBankCreate, QuestionCreate
from ..schemas.user import AnswerSubmit, AnswerResult
from ..services.doc_parser import parse_document, split_text_into_chunks
from ..services.ai_engine import generate_questions_from_chunks, classify_questions_tags

logger = logging.getLogger(__name__)


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
    query = db.query(Question).filter(
        Question.bank_id == bank_id,
        Question.status == "active",
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

    results = []
    for record in unique[:100]:
        q = db.query(Question).filter(Question.id == record.question_id).first()
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


def get_starred_questions(db: Session, user_id: int, bank_id: int) -> List[Question]:
    progress = db.query(UserProgress).filter(
        UserProgress.user_id == user_id,
        UserProgress.bank_id == bank_id,
    ).first()
    if not progress or not progress.starred_ids:
        return []
    return db.query(Question).filter(Question.id.in_(progress.starred_ids)).all()


# ──────────────────────────────────────────
#  答题逻辑
# ──────────────────────────────────────────

def submit_answer(db: Session, data: AnswerSubmit) -> AnswerResult:
    question = db.query(Question).filter(Question.id == data.question_id).first()
    if not question:
        raise ValueError("题目不存在")

    # 判断对错（多选题需要答案集合相同）
    correct_set = set(question.answer.upper())
    user_set = set(data.user_answer.upper())
    is_correct = correct_set == user_set

    # 写入答题记录
    record = AnswerRecord(
        user_id=data.user_id,
        question_id=data.question_id,
        bank_id=data.bank_id,
        user_answer=data.user_answer,
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
    progress = db.query(UserProgress).filter(
        UserProgress.user_id == data.user_id,
        UserProgress.bank_id == data.bank_id,
    ).first()
    if not progress:
        progress = UserProgress(
            user_id=data.user_id,
            bank_id=data.bank_id,
            starred_ids=[],
        )
        db.add(progress)
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
    progress = db.query(UserProgress).filter(
        UserProgress.user_id == user_id,
        UserProgress.bank_id == bank_id,
    ).first()
    if not progress:
        progress = UserProgress(user_id=user_id, bank_id=bank_id, starred_ids=[])
        db.add(progress)

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
    progress = db.query(UserProgress).filter(
        UserProgress.user_id == user_id,
        UserProgress.bank_id == bank_id,
    ).first()
    if not progress:
        progress = UserProgress(user_id=user_id, bank_id=bank_id, starred_ids=[])
        db.add(progress)
    progress.last_position = position
    db.commit()


# ──────────────────────────────────────────
#  用户统计
# ──────────────────────────────────────────

def get_user_stats(db: Session, user_id: int) -> dict:
    from datetime import date, datetime, timedelta

    total_records = db.query(AnswerRecord).filter(AnswerRecord.user_id == user_id).count()
    correct_records = db.query(AnswerRecord).filter(
        AnswerRecord.user_id == user_id,
        AnswerRecord.is_correct == True,
    ).count()
    wrong_count = total_records - correct_records

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

    return {
        "total_answered": total_records,
        "correct_count": correct_records,
        "accuracy": accuracy,
        "banks_studied": banks_studied,
        "wrong_count": wrong_count,
        "starred_count": starred_count,
        "today_answered": today_answered,
        "streak_days": 1,  # 简化实现，生产可计算连续天数
    }


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
        task = db.query(GenerateTask).filter(GenerateTask.id == task_id).first()
        if not task:
            return

        task.status = TaskStatus.running
        task.message = "正在解析文档..."
        db.commit()

        # 1. 解析文档
        text = await parse_document(file_path, source_type)
        if not text.strip():
            raise ValueError("文档内容为空，请检查文件")

        # 2. 分块
        chunks = split_text_into_chunks(text)
        task.total_chunks = len(chunks)
        task.message = f"文档已分为 {len(chunks)} 个段落，开始出题..."
        db.commit()

        # 3. 进度回调
        async def on_progress(processed: int, total: int, generated: int, msg: str):
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

        # 5. 补全标签
        task.message = "正在整理知识点标签..."
        db.commit()
        questions = await classify_questions_tags(questions)

        # 6. 批量写入数据库
        for i, q in enumerate(questions):
            q["order_index"] = i
            db.add(Question(**q))

        bank = db.query(QuestionBank).filter(QuestionBank.id == bank_id).first()
        if bank:
            bank.total_count = len(questions)
            bank.status = BankStatus.ready

        task.status = TaskStatus.done
        task.progress = 100
        task.generated_count = len(questions)
        task.message = f"出题完成！共生成 {len(questions)} 道题目"
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
