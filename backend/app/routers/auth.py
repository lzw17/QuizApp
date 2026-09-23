"""
微信登录路由
POST /api/auth/login          微信小程序 code 换 openid，返回用户信息
GET  /api/auth/me             校验应用登录态并返回当前用户
POST /api/auth/avatar         上传头像图片
PUT  /api/auth/profile        更新昵称/头像 URL
"""
import os
import re
import uuid
import logging
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import create_access_token, get_current_user, is_configured_admin
from ..database import get_db
from ..models.question import (
    BankStatus,
    ExamSubmission,
    ExamSession,
    GenerateTask,
    GenerationBatch,
    Question,
    QuestionBank,
    BatchStatus,
    TaskStatus,
)
from ..models.user import AnswerRecord, User, UserProgress
from ..schemas.user import UserOut
from ..config import settings
from ..utils.time import utc_now

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)

WX_CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"


class LoginRequest(BaseModel):
    code: str = Field(min_length=1, max_length=128)


class WeChatSession(BaseModel):
    """Identity returned by code2Session; never serialized to the mini program."""

    openid: str
    session_key: str
    unionid: Optional[str] = None


class LoginResponse(BaseModel):
    user: UserOut
    is_new: bool
    access_token: str
    token_type: str = "Bearer"
    expires_in: int


@router.post("/login", response_model=LoginResponse)
async def wx_login(data: LoginRequest, db: Session = Depends(get_db)):
    """
    微信小程序登录：用 code 换取 openid
    仅开发环境显式开启 WX_MOCK_LOGIN 时使用固定 mock 身份
    """
    wechat_session = await _get_wechat_session(data.code.strip())
    openid = wechat_session.openid

    user = db.query(User).filter(User.openid == openid).first()
    is_new = False
    if not user:
        user = User(
            openid=openid,
            nickname="微信用户",
        )
        db.add(user)
        try:
            db.commit()
            db.refresh(user)
            is_new = True
        except IntegrityError:
            # Two concurrent wx.login calls for the same user may race on creation.
            db.rollback()
            user = db.query(User).filter(User.openid == openid).first()
            if not user:
                raise HTTPException(500, "创建用户失败")

    user.is_admin = is_configured_admin(openid)

    user.last_login = utc_now()
    db.commit()
    db.refresh(user)
    access_token, expires_in = create_access_token(user.id, user.token_version or 0)

    return LoginResponse(
        user=UserOut.model_validate(user),
        is_new=is_new,
        access_token=access_token,
        expires_in=expires_in,
    )


@router.get("/me", response_model=UserOut)
def get_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Validate the application session and return the current user."""
    return UserOut.model_validate(current_user)


@router.post("/logout")
def logout(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """递增服务端 token 版本，使已签发的登录态立即失效。"""
    current_user.token_version = (current_user.token_version or 0) + 1
    db.commit()
    return {"message": "已退出登录"}


@router.delete("/account")
def delete_account(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Anonymize and disable an account, then revoke every active token."""
    old_openid = current_user.openid
    old_avatar = current_user.avatar or ""
    owned_banks = db.query(
        QuestionBank.id,
        QuestionBank.source_file,
        QuestionBank.source_type,
    ).filter(QuestionBank.created_by == old_openid).all()
    owned_bank_ids = [bank.id for bank in owned_banks]
    owned_sources = [
        (bank.source_file, bank.source_type)
        for bank in owned_banks
        if bank.source_file and bank.source_type != "url"
    ]
    db.query(AnswerRecord).filter(AnswerRecord.user_id == current_user.id).delete(
        synchronize_session=False
    )
    db.query(UserProgress).filter(UserProgress.user_id == current_user.id).delete(
        synchronize_session=False
    )
    db.query(ExamSubmission).filter(ExamSubmission.user_id == current_user.id).delete(
        synchronize_session=False
    )
    db.query(ExamSession).filter(ExamSession.user_id == current_user.id).delete(
        synchronize_session=False
    )
    if owned_bank_ids:
        db.query(Question).filter(Question.bank_id.in_(owned_bank_ids)).update(
            {
                Question.content: "",
                Question.options: [],
                Question.answer: "",
                Question.explanation: "",
                Question.tags: [],
                Question.status: "deleted",
            },
            synchronize_session=False,
        )
        db.query(QuestionBank).filter(QuestionBank.id.in_(owned_bank_ids)).update(
            {
                QuestionBank.name: "已删除题库",
                QuestionBank.description: "",
                QuestionBank.cover: "",
                QuestionBank.category: "",
                QuestionBank.total_count: 0,
                QuestionBank.source_file: "",
                QuestionBank.source_type: "",
                QuestionBank.created_by: "",
                QuestionBank.status: BankStatus.deleted,
            },
            synchronize_session=False,
        )
        db.query(GenerateTask).filter(
            GenerateTask.bank_id.in_(owned_bank_ids),
            GenerateTask.status.in_([TaskStatus.pending, TaskStatus.running]),
        ).update(
            {
                GenerateTask.status: TaskStatus.failed,
                GenerateTask.message: "账号已注销，生成任务已终止",
                GenerateTask.error: "account deleted",
            },
            synchronize_session=False,
        )
        db.query(GenerationBatch).filter(
            GenerationBatch.bank_id.in_(owned_bank_ids),
            GenerationBatch.status.in_([BatchStatus.pending, BatchStatus.running]),
        ).update(
            {
                GenerationBatch.status: BatchStatus.failed,
                GenerationBatch.error: "account deleted",
                GenerationBatch.completed_at: utc_now(),
            },
            synchronize_session=False,
        )
        db.query(GenerationBatch).filter(
            GenerationBatch.bank_id.in_(owned_bank_ids),
        ).update({GenerationBatch.source_text: None}, synchronize_session=False)
    current_user.openid = f"deleted_{uuid.uuid4().hex}"
    current_user.nickname = ""
    current_user.avatar = ""
    current_user.is_admin = False
    current_user.is_active = False
    current_user.token_version = (current_user.token_version or 0) + 1
    db.commit()
    for source_file, source_type in owned_sources:
        _remove_owned_source_file(source_file, source_type)
    _remove_owned_avatar(old_avatar)
    return {"message": "Account deleted"}


def _remove_owned_source_file(source_file: str, source_type: str) -> None:
    """Delete only generated PDF/DOCX uploads in the configured upload root."""
    expected_extension = {"pdf": ".pdf", "word": ".docx"}.get(source_type)
    if not source_file or not expected_extension:
        return
    upload_dir = os.path.realpath(settings.UPLOAD_DIR)
    candidate = os.path.realpath(source_file)
    if os.path.dirname(candidate) != upload_dir:
        return
    filename = os.path.basename(candidate)
    if not re.fullmatch(
        rf"[0-9a-f]{{8}}-(?:[0-9a-f]{{4}}-){{3}}[0-9a-f]{{12}}{re.escape(expected_extension)}",
        filename,
    ):
        return
    try:
        os.remove(candidate)
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("无法清理注销账号的源文件 %s", candidate, exc_info=True)


def _remove_owned_avatar(avatar_url: str) -> None:
    """Delete only files inside the configured avatar directory."""
    if not avatar_url:
        return
    parsed = urlparse(avatar_url)
    configured_base = settings.PUBLIC_BASE_URL.strip().rstrip("/")
    if configured_base:
        base = urlparse(configured_base)
        if parsed.scheme != base.scheme or parsed.netloc != base.netloc:
            return
    elif parsed.scheme or parsed.netloc:
        return
    prefix = "/uploads/avatars/"
    if not parsed.path.startswith(prefix):
        return
    filename = parsed.path[len(prefix):]
    if not re.fullmatch(r"[0-9a-f]{32}\.(?:jpg|jpeg|png|webp|gif)", filename):
        return
    avatar_dir = os.path.realpath(os.path.join(settings.UPLOAD_DIR, "avatars"))
    candidate = os.path.realpath(os.path.join(avatar_dir, filename))
    if os.path.dirname(candidate) != avatar_dir:
        return
    try:
        os.remove(candidate)
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("无法清理头像文件 %s", candidate, exc_info=True)


@router.post("/avatar")
async def upload_avatar(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上传用户头像，返回可访问的 URL"""
    ext = os.path.splitext(file.filename or ".jpg")[1].lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        raise HTTPException(400, "仅支持图片格式（jpg/png/webp/gif）")
    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(400, "上传文件不是有效图片")

    max_size = 5 * 1024 * 1024
    content = await file.read(max_size + 1)
    if len(content) > max_size:
        raise HTTPException(400, "头像文件不能超过 5MB")
    if not _valid_image_signature(content, ext):
        raise HTTPException(400, "头像文件内容无效")

    avatar_dir = os.path.join(settings.UPLOAD_DIR, "avatars")
    os.makedirs(avatar_dir, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    save_path = os.path.join(avatar_dir, filename)
    with open(save_path, "wb") as f:
        f.write(content)

    base = settings.PUBLIC_BASE_URL.strip().rstrip("/") or str(request.base_url).rstrip("/")
    full_url = f"{base}/uploads/avatars/{filename}"

    old_avatar = current_user.avatar or ""
    current_user.avatar = full_url
    db.commit()
    db.refresh(current_user)
    _remove_owned_avatar(old_avatar)

    return {"avatar_url": full_url}


def _valid_image_signature(content: bytes, ext: str) -> bool:
    signatures = {
        ".jpg": content.startswith(b"\xff\xd8\xff"),
        ".jpeg": content.startswith(b"\xff\xd8\xff"),
        ".png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        ".gif": content.startswith((b"GIF87a", b"GIF89a")),
        ".webp": content.startswith(b"RIFF") and content[8:12] == b"WEBP",
    }
    return signatures.get(ext, False)


class ProfileUpdate(BaseModel):
    nickname: str = Field(default="", max_length=20)
    avatar: str = Field(default="", max_length=500)


@router.put("/profile", response_model=UserOut)
def update_profile(
    data: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update profile text; avatar replacement is handled only by /avatar."""
    nickname = data.nickname.strip()
    if nickname:
        current_user.nickname = nickname
    old_avatar = ""
    if data.avatar != (current_user.avatar or ""):
        if data.avatar:
            raise HTTPException(400, "请通过头像上传接口更换头像")
        old_avatar = current_user.avatar or ""
        current_user.avatar = ""
    db.commit()
    db.refresh(current_user)
    if old_avatar:
        _remove_owned_avatar(old_avatar)
    return UserOut.model_validate(current_user)


async def _get_wechat_session(code: str) -> WeChatSession:
    """Exchange a one-time code for a trusted server-side WeChat session."""
    if settings.WX_MOCK_LOGIN:
        if settings.APP_ENV.lower() != "development":
            raise HTTPException(500, "生产环境禁止使用模拟微信登录")
        return WeChatSession(
            openid=f"mock_{settings.WX_MOCK_OPENID}",
            session_key="mock-session-key",
        )

    if not settings.WX_APPID or not settings.WX_SECRET:
        raise HTTPException(503, "微信登录尚未配置")

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                WX_CODE2SESSION_URL,
                params={
                    "appid": settings.WX_APPID,
                    "secret": settings.WX_SECRET,
                    "js_code": code,
                    "grant_type": "authorization_code",
                },
            )
            resp.raise_for_status()
            result = resp.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, "微信服务暂时不可用，请稍后重试")

    errcode = result.get("errcode", 0)
    if errcode != 0:
        if errcode in (40029, 40163):
            raise HTTPException(400, "微信登录凭证无效或已使用，请重试")
        if errcode == 45011:
            raise HTTPException(429, "登录过于频繁，请稍后重试")
        raise HTTPException(502, "微信登录服务返回异常")
    if not result.get("openid"):
        raise HTTPException(502, "微信登录响应缺少用户标识")
    if not result.get("session_key"):
        raise HTTPException(502, "微信登录响应缺少会话密钥")
    return WeChatSession.model_validate(result)
