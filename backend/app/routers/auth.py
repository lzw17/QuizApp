"""
微信登录路由
POST /api/auth/login          微信小程序 code 换 openid，返回用户信息
GET  /api/auth/me             校验应用登录态并返回当前用户
POST /api/auth/avatar         上传头像图片
PUT  /api/auth/profile        更新昵称/头像 URL
"""
import os
import uuid
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import create_access_token, get_current_user
from ..database import get_db
from ..models.user import User
from ..schemas.user import UserOut
from ..config import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

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

    user.last_login = datetime.utcnow()
    db.commit()
    db.refresh(user)
    access_token, expires_in = create_access_token(user.id)

    return LoginResponse(
        user=UserOut.model_validate(user),
        is_new=is_new,
        access_token=access_token,
        expires_in=expires_in,
    )


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    """Validate the application session and return the current user."""
    return UserOut.model_validate(current_user)


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

    avatar_dir = os.path.join(settings.UPLOAD_DIR, "avatars")
    os.makedirs(avatar_dir, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    save_path = os.path.join(avatar_dir, filename)
    with open(save_path, "wb") as f:
        f.write(content)

    base = str(request.base_url).rstrip("/")
    full_url = f"{base}/uploads/avatars/{filename}"

    current_user.avatar = full_url
    db.commit()
    db.refresh(current_user)

    return {"avatar_url": full_url}


class ProfileUpdate(BaseModel):
    nickname: str = Field(default="", max_length=20)
    avatar: str = Field(default="", max_length=500)


@router.put("/profile", response_model=UserOut)
def update_profile(
    data: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新用户昵称或头像 URL"""
    nickname = data.nickname.strip()
    if nickname:
        current_user.nickname = nickname
    if data.avatar:
        current_user.avatar = data.avatar
    db.commit()
    db.refresh(current_user)
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
