"""
题库 & 题目查询路由
GET  /api/banks              题库列表
GET  /api/banks/{id}         题库详情
GET  /api/questions          分页获取题目
GET  /api/questions/{id}     单题详情
PUT  /api/questions/{id}     编辑题目（管理员）
DELETE /api/questions/{id}   删除题目（管理员）
GET  /api/banks/{id}/tags    获取题库知识点标签列表
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func as sa_func

from ..database import get_db
from ..models.question import QuestionBank, Question, BankStatus
from ..models.user import AnswerRecord, UserProgress
from ..schemas.question import QuestionBankListItem, QuestionBankOut, QuestionOut, QuestionCreate

router = APIRouter(prefix="/api", tags=["questions"])


@router.get("/banks", response_model=List[QuestionBankListItem])
def list_banks(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    category: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(QuestionBank).filter(QuestionBank.status == BankStatus.ready)
    if category:
        query = query.filter(QuestionBank.category == category)
    return query.order_by(QuestionBank.id.desc()).offset(skip).limit(limit).all()


@router.get("/banks/all", response_model=List[QuestionBankListItem])
def list_all_banks(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """管理员：获取所有状态的题库"""
    return db.query(QuestionBank).order_by(QuestionBank.id.desc()).offset(skip).limit(limit).all()


@router.get("/banks/{bank_id}", response_model=QuestionBankOut)
def get_bank_detail(bank_id: int, db: Session = Depends(get_db)):
    bank = db.query(QuestionBank).filter(QuestionBank.id == bank_id).first()
    if not bank:
        raise HTTPException(404, "题库不存在")

    # 动态聚合所有标签
    questions = db.query(Question).filter(
        Question.bank_id == bank_id,
        Question.status == "active",
    ).all()
    tag_set = set()
    for q in questions:
        for t in (q.tags or []):
            tag_set.add(str(t))

    result = QuestionBankOut.model_validate(bank)
    result.tags = sorted(tag_set)
    return result


@router.get("/banks/{bank_id}/tags", response_model=List[str])
def get_bank_tags(bank_id: int, db: Session = Depends(get_db)):
    """获取题库所有知识点标签（用于分类练习筛选）"""
    questions = db.query(Question.tags).filter(
        Question.bank_id == bank_id,
        Question.status == "active",
    ).all()
    tag_set = set()
    for (tags,) in questions:
        for t in (tags or []):
            tag_set.add(str(t))
    return sorted(tag_set)


@router.get("/questions", response_model=List[QuestionOut])
def get_questions(
    bank_id: int = Query(...),
    mode: str = Query("sequential", description="sequential/random/wrong/starred"),
    user_id: Optional[int] = None,
    tag: Optional[str] = None,
    difficulty: Optional[int] = Query(None, ge=1, le=5),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(Question).filter(
        Question.bank_id == bank_id,
        Question.status == "active",
    )

    ordered_ids: Optional[List[int]] = None
    if mode == "wrong":
        if not user_id:
            raise HTTPException(400, "错题练习需要 user_id")
        records = db.query(AnswerRecord).filter(
            AnswerRecord.user_id == user_id,
            AnswerRecord.bank_id == bank_id,
            AnswerRecord.is_correct == False,
        ).order_by(AnswerRecord.answered_at.desc()).all()
        ordered_ids = []
        seen = set()
        for record in records:
            if record.question_id not in seen:
                seen.add(record.question_id)
                ordered_ids.append(record.question_id)
        if not ordered_ids:
            return []
        query = query.filter(Question.id.in_(ordered_ids))
    elif mode == "starred":
        if not user_id:
            raise HTTPException(400, "收藏练习需要 user_id")
        progress = db.query(UserProgress).filter(
            UserProgress.user_id == user_id,
            UserProgress.bank_id == bank_id,
        ).first()
        ordered_ids = list(progress.starred_ids or []) if progress else []
        if not ordered_ids:
            return []
        query = query.filter(Question.id.in_(ordered_ids))

    if tag:
        query = query.filter(Question.tags.contains(f'"{tag}"'))
    if difficulty:
        query = query.filter(Question.difficulty == difficulty)

    if mode == "random":
        query = query.order_by(sa_func.random())
    elif ordered_ids is not None:
        questions = query.all()
        by_id = {q.id: q for q in questions}
        ordered = [by_id[qid] for qid in ordered_ids if qid in by_id]
        return ordered[skip:skip + limit]
    else:
        query = query.order_by(Question.order_index)

    return query.offset(skip).limit(limit).all()


@router.get("/questions/{question_id}", response_model=QuestionOut)
def get_question(question_id: int, db: Session = Depends(get_db)):
    q = db.query(Question).filter(Question.id == question_id).first()
    if not q:
        raise HTTPException(404, "题目不存在")
    return q


@router.post("/questions", response_model=QuestionOut)
def create_question(data: QuestionCreate, db: Session = Depends(get_db)):
    """手动添加题目"""
    bank = db.query(QuestionBank).filter(QuestionBank.id == data.bank_id).first()
    if not bank:
        raise HTTPException(404, "题库不存在")

    # 确定 order_index
    max_idx = db.query(sa_func.max(Question.order_index)).filter(
        Question.bank_id == data.bank_id
    ).scalar() or 0

    q = Question(
        bank_id=data.bank_id,
        type=data.type,
        content=data.content,
        options=[o.model_dump() for o in data.options],
        answer=data.answer,
        explanation=data.explanation,
        tags=data.tags,
        difficulty=data.difficulty,
        order_index=max_idx + 1,
    )
    db.add(q)
    bank.total_count += 1
    db.commit()
    db.refresh(q)
    return q


@router.put("/questions/{question_id}", response_model=QuestionOut)
def update_question(question_id: int, data: QuestionCreate, db: Session = Depends(get_db)):
    q = db.query(Question).filter(Question.id == question_id).first()
    if not q:
        raise HTTPException(404, "题目不存在")
    q.type = data.type
    q.content = data.content
    q.options = [o.model_dump() for o in data.options]
    q.answer = data.answer
    q.explanation = data.explanation
    q.tags = data.tags
    q.difficulty = data.difficulty
    db.commit()
    db.refresh(q)
    return q


@router.delete("/questions/{question_id}")
def delete_question(question_id: int, db: Session = Depends(get_db)):
    q = db.query(Question).filter(Question.id == question_id).first()
    if not q:
        raise HTTPException(404, "题目不存在")
    q.status = "deleted"
    bank = db.query(QuestionBank).filter(QuestionBank.id == q.bank_id).first()
    if bank and bank.total_count > 0:
        bank.total_count -= 1
    db.commit()
    return {"message": "删除成功"}
