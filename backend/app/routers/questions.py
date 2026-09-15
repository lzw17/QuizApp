"""
题库 & 题目查询路由
GET  /api/banks              题库列表
GET  /api/banks/{id}         题库详情
DELETE /api/banks/{id}       删除题库（创建者或管理员）
GET  /api/questions          分页获取题目
GET  /api/questions/{id}     单题详情
PUT  /api/questions/{id}     编辑题目（管理员）
DELETE /api/questions/{id}   删除题目（管理员）
GET  /api/banks/{id}/tags    获取题库知识点标签列表
"""
import os
import random
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func as sa_func

from ..auth import get_current_user, require_admin
from ..database import get_db
from ..models.question import GenerateTask, QuestionBank, Question, BankStatus, TaskStatus
from ..models.user import User, UserProgress
from ..schemas.question import QuestionBankListItem, QuestionBankOut, QuestionOut, QuestionPublicOut, QuestionCreate
from ..services.question_service import get_current_wrong_question_ids

router = APIRouter(prefix="/api", tags=["questions"])


def _can_delete_bank(bank: QuestionBank, user: User) -> bool:
    return bool(user.is_admin or (bank.created_by and bank.created_by == user.openid))


def _bank_list_item(bank: QuestionBank, user: User) -> QuestionBankListItem:
    item = QuestionBankListItem.model_validate(bank)
    item.can_delete = _can_delete_bank(bank, user)
    return item


def _get_visible_bank(db: Session, bank_id: int, user: User) -> QuestionBank:
    bank = db.query(QuestionBank).filter(
        QuestionBank.id == bank_id,
        QuestionBank.status != BankStatus.deleted,
    ).first()
    if not bank or (not user.is_admin and bank.status != BankStatus.ready):
        raise HTTPException(404, "题库不存在")
    return bank


@router.get("/banks", response_model=List[QuestionBankListItem])
def list_banks(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    category: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(QuestionBank).filter(QuestionBank.status == BankStatus.ready)
    if category:
        query = query.filter(QuestionBank.category == category)
    banks = query.order_by(QuestionBank.id.desc()).offset(skip).limit(limit).all()
    return [_bank_list_item(bank, current_user) for bank in banks]


@router.get("/banks/all", response_model=List[QuestionBankListItem])
def list_all_banks(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """管理员：获取所有状态的题库"""
    banks = db.query(QuestionBank).filter(
        QuestionBank.status != BankStatus.deleted,
    ).order_by(QuestionBank.id.desc()).offset(skip).limit(limit).all()
    return [_bank_list_item(bank, admin) for bank in banks]


@router.get("/banks/{bank_id}", response_model=QuestionBankOut)
def get_bank_detail(
    bank_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bank = _get_visible_bank(db, bank_id, current_user)

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
    result.can_delete = _can_delete_bank(bank, current_user)
    return result


@router.get("/banks/{bank_id}/tags", response_model=List[str])
def get_bank_tags(
    bank_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取题库所有知识点标签（用于分类练习筛选）"""
    _get_visible_bank(db, bank_id, current_user)
    questions = db.query(Question.tags).filter(
        Question.bank_id == bank_id,
        Question.status == "active",
    ).all()
    tag_set = set()
    for (tags,) in questions:
        for t in (tags or []):
            tag_set.add(str(t))
    return sorted(tag_set)


@router.delete("/banks/{bank_id}")
def delete_bank(
    bank_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Soft-delete a bank while preserving historical learning records."""
    bank = db.query(QuestionBank).filter(
        QuestionBank.id == bank_id,
        QuestionBank.status != BankStatus.deleted,
    ).first()
    if not bank:
        raise HTTPException(404, "题库不存在")
    if not _can_delete_bank(bank, current_user):
        raise HTTPException(403, "只能删除自己创建的题库")

    deleted_questions = db.query(Question).filter(
        Question.bank_id == bank_id,
        Question.status != "deleted",
    ).update({Question.status: "deleted"}, synchronize_session=False)

    active_tasks = db.query(GenerateTask).filter(
        GenerateTask.bank_id == bank_id,
        GenerateTask.status.in_([TaskStatus.pending, TaskStatus.running]),
    ).all()
    for task in active_tasks:
        task.status = TaskStatus.failed
        task.message = "题库已删除，生成已停止"
        task.error = "bank deleted"

    bank.status = BankStatus.deleted
    db.commit()
    if bank.source_type != "url" and bank.source_file and os.path.isfile(bank.source_file):
        try:
            os.remove(bank.source_file)
        except OSError:
            pass
    return {
        "message": "题库已删除",
        "bank_id": bank_id,
        "deleted_questions": deleted_questions,
    }


@router.get("/questions", response_model=List[QuestionPublicOut])
def get_questions(
    bank_id: int = Query(...),
    mode: str = Query("sequential", description="sequential/random/wrong/starred"),
    tag: Optional[str] = None,
    difficulty: Optional[int] = Query(None, ge=1, le=5),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    seed: Optional[int] = Query(None, ge=0, le=2147483647),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_visible_bank(db, bank_id, current_user)
    if mode not in ("sequential", "random", "wrong", "starred"):
        raise HTTPException(400, "不支持的题目模式")

    query = db.query(Question).filter(
        Question.bank_id == bank_id,
        Question.status == "active",
    )

    ordered_ids: Optional[List[int]] = None
    if mode == "wrong":
        ordered_ids = get_current_wrong_question_ids(db, current_user.id, bank_id)
        if not ordered_ids:
            return []
        query = query.filter(Question.id.in_(ordered_ids))
    elif mode == "starred":
        progress = db.query(UserProgress).filter(
            UserProgress.user_id == current_user.id,
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
        # A stable seed lets the mini program request later pages without
        # reshuffling the first page and producing duplicates or gaps.
        if seed is not None:
            questions = query.order_by(Question.id).all()
            random.Random(seed).shuffle(questions)
            return questions[skip:skip + limit]
        query = query.order_by(sa_func.random())
    elif ordered_ids is not None:
        questions = query.all()
        by_id = {q.id: q for q in questions}
        ordered = [by_id[qid] for qid in ordered_ids if qid in by_id]
        return ordered[skip:skip + limit]
    else:
        query = query.order_by(Question.order_index)

    return query.offset(skip).limit(limit).all()


@router.get("/questions/count")
def count_questions(
    bank_id: int = Query(...),
    mode: str = Query("sequential"),
    tag: Optional[str] = None,
    difficulty: Optional[int] = Query(None, ge=1, le=5),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """返回当前筛选条件下的题目总数，供前端分页加载使用。"""
    _get_visible_bank(db, bank_id, current_user)
    query = db.query(Question).filter(
        Question.bank_id == bank_id,
        Question.status == "active",
    )
    if mode == "wrong":
        ids = get_current_wrong_question_ids(db, current_user.id, bank_id)
        query = query.filter(Question.id.in_(ids)) if ids else query.filter(Question.id == -1)
    elif mode == "starred":
        progress = db.query(UserProgress).filter(
            UserProgress.user_id == current_user.id,
            UserProgress.bank_id == bank_id,
        ).first()
        ids = list(progress.starred_ids or []) if progress else []
        query = query.filter(Question.id.in_(ids)) if ids else query.filter(Question.id == -1)
    elif mode not in ("sequential", "random"):
        raise HTTPException(400, "不支持的题目模式")
    if tag:
        query = query.filter(Question.tags.contains(f'"{tag}"'))
    if difficulty:
        query = query.filter(Question.difficulty == difficulty)
    return {"total": query.count()}


@router.get("/admin/questions", response_model=List[QuestionOut])
def list_admin_questions(
    bank_id: int = Query(...),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """管理员编辑题目时使用，标准答案只对管理员返回。"""
    return db.query(Question).filter(
        Question.bank_id == bank_id,
        Question.status == "active",
    ).order_by(Question.order_index).offset(skip).limit(limit).all()


@router.get("/questions/{question_id}", response_model=QuestionPublicOut)
def get_question(
    question_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Question).join(QuestionBank).filter(
        Question.id == question_id,
        Question.status == "active",
        QuestionBank.status != BankStatus.deleted,
    ).first()
    if not q or (not current_user.is_admin and q.bank.status != BankStatus.ready):
        raise HTTPException(404, "题目不存在")
    return q


@router.post("/questions", response_model=QuestionOut)
def create_question(
    data: QuestionCreate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """手动添加题目"""
    bank = db.query(QuestionBank).filter(
        QuestionBank.id == data.bank_id,
        QuestionBank.status != BankStatus.deleted,
    ).first()
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
def update_question(
    question_id: int,
    data: QuestionCreate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = db.query(Question).join(QuestionBank).filter(
        Question.id == question_id,
        Question.status == "active",
        QuestionBank.status != BankStatus.deleted,
    ).first()
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
def delete_question(
    question_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = db.query(Question).join(QuestionBank).filter(
        Question.id == question_id,
        Question.status == "active",
        QuestionBank.status != BankStatus.deleted,
    ).first()
    if not q:
        raise HTTPException(404, "题目不存在")
    q.status = "deleted"
    bank = db.query(QuestionBank).filter(QuestionBank.id == q.bank_id).first()
    if bank and bank.total_count > 0:
        bank.total_count -= 1
    db.commit()
    return {"message": "删除成功"}
