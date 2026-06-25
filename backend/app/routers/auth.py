"""
微信登录路由
POST /api/auth/login   微信小程序 code 换 openid，返回用户信息
"""
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from ..schemas.user import UserOut
from ..config import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

WX_CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"


class LoginRequest(BaseModel):
    code: str
    nickname: str = ""
    avatar: str = ""


class LoginResponse(BaseModel):
    user: UserOut
    is_new: bool


@router.post("/login", response_model=LoginResponse)
async def wx_login(data: LoginRequest, db: Session = Depends(get_db)):
    """
    微信小程序登录：用 code 换取 openid
    开发模式下若未配置 APPID/SECRET，使用 code 作为 mock openid
    """
    openid = await _get_openid(data.code)

    user = db.query(User).filter(User.openid == openid).first()
    is_new = False
    if not user:
        user = User(
            openid=openid,
            nickname=data.nickname or f"用户{openid[-6:]}",
            avatar=data.avatar,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        is_new = True
    else:
        if data.nickname:
            user.nickname = data.nickname
        if data.avatar:
            user.avatar = data.avatar
        db.commit()
        db.refresh(user)

    return LoginResponse(user=UserOut.model_validate(user), is_new=is_new)


async def _get_openid(code: str) -> str:
    """通过微信 code 换取 openid（未配置时走 mock）"""
    appid = getattr(settings, "WX_APPID", "")
    secret = getattr(settings, "WX_SECRET", "")

    if not appid or not secret:
        # 开发模式：直接用 code 作为 mock openid
        return f"mock_{code}"

    async with httpx.AsyncClient() as client:
        resp = await client.get(WX_CODE2SESSION_URL, params={
            "appid": appid,
            "secret": secret,
            "js_code": code,
            "grant_type": "authorization_code",
        })
        data = resp.json()
        if "errcode" in data and data["errcode"] != 0:
            raise HTTPException(400, f"微信登录失败: {data.get('errmsg')}")
        return data["openid"]
