"""IP→用户名绑定路由:panel 前端 SPA 查当前 IP 的用户名 + 绑定/改名。

与 InfoWeb 共用 MySQL 的 user_ip 表;未绑定 IP 首次使用时前端提示输入名字。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.v1.case_tags import _client_ip
from app.db.mysql import get_mysql_db
from app.models.user import User
from app.services.case_tags import bind_username, get_username_by_ip

router = APIRouter(prefix="/user-bindings", tags=["user-bindings"])

MAX_USERNAME_LEN = 32


class CurrentBindingOut(BaseModel):
    ip: str
    username: str | None


class BindIn(BaseModel):
    username: str


@router.get("/current", response_model=CurrentBindingOut)
async def current_binding(
    request: Request,
    mysql_db: AsyncSession = Depends(get_mysql_db),
    _current_user: User = Depends(get_current_user),
) -> CurrentBindingOut:
    ip = _client_ip(request)
    username = await get_username_by_ip(mysql_db, ip) if ip else None
    return CurrentBindingOut(ip=ip, username=username)


@router.put("/current", response_model=CurrentBindingOut)
async def bind_current(
    payload: BindIn,
    request: Request,
    mysql_db: AsyncSession = Depends(get_mysql_db),
    _current_user: User = Depends(get_current_user),
) -> CurrentBindingOut:
    ip = _client_ip(request)
    if not ip:
        raise HTTPException(status_code=400, detail="无法识别客户端 IP")
    username = (payload.username or "").strip()
    if not username:
        raise HTTPException(status_code=422, detail="用户名不能为空")
    if len(username) > MAX_USERNAME_LEN:
        raise HTTPException(status_code=422, detail=f"用户名过长(最多 {MAX_USERNAME_LEN} 字)")
    await bind_username(mysql_db, ip, username)
    return CurrentBindingOut(ip=ip, username=username)
