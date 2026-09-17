"""Central question-bank visibility rules."""
from fastapi import HTTPException
from sqlalchemy.orm import Query, Session

from ..models.question import BankStatus, QuestionBank
from ..models.user import User


def apply_bank_access(query: Query, user: User, *, require_ready: bool = True) -> Query:
    if require_ready:
        query = query.filter(QuestionBank.status == BankStatus.ready)
    else:
        query = query.filter(QuestionBank.status != BankStatus.deleted)
    if not user.is_admin:
        query = query.filter(QuestionBank.created_by == user.openid)
    return query


def get_accessible_bank(
    db: Session,
    bank_id: int,
    user: User,
    *,
    require_ready: bool = True,
) -> QuestionBank:
    query = db.query(QuestionBank).filter(QuestionBank.id == bank_id)
    bank = apply_bank_access(query, user, require_ready=require_ready).first()
    if not bank:
        raise HTTPException(404, "题库不存在")
    return bank
