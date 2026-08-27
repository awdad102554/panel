"""记事本快捷内容路由:所有用户共享的常用记事短句,与 InfoWeb 共用同一张 MySQL 表。

快捷内容在记事本弹窗中以可点选的标签展示,点击填入记事输入框;任何用户都可增删。
创建人(operator)由客户端 IP 查 user_ip 绑定解析,未绑定则要求先设置用户名。
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, field_serializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.v1.case_tags import _client_ip
from app.db.mysql import get_mysql_db
from app.models.case_tag import CaseTagPhrase
from app.models.user import User
from app.services.case_tags import get_username_by_ip, normalize_phrase

router = APIRouter(prefix="/case-tag-phrases", tags=["case-tag-phrases"])


class PhraseCreate(BaseModel):
    content: str


class PhraseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    content: str
    operator: str
    created_at: datetime

    @field_serializer("created_at")
    def _ser_created_at(self, v: datetime) -> datetime:
        # MySQL DATETIME 读回为 naive(UTC 墙钟),补 UTC 时区,前端 new Date 才能转本地。
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v


@router.get("", response_model=list[PhraseOut])
async def list_phrases(
    mysql_db: AsyncSession = Depends(get_mysql_db),
    _current_user: User = Depends(get_current_user),
) -> list[PhraseOut]:
    """列出全部快捷内容(按创建时间正序)。"""
    stmt = select(CaseTagPhrase).order_by(CaseTagPhrase.created_at.asc(), CaseTagPhrase.id.asc())
    return list((await mysql_db.execute(stmt)).scalars().all())


@router.post("", response_model=PhraseOut)
async def create_phrase(
    payload: PhraseCreate,
    request: Request,
    mysql_db: AsyncSession = Depends(get_mysql_db),
    _current_user: User = Depends(get_current_user),
) -> PhraseOut:
    """新增一条快捷内容:内容唯一去重,已存在时直接返回原条目(幂等)。"""
    try:
        content = normalize_phrase(payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    ip = _client_ip(request)
    operator = await get_username_by_ip(mysql_db, ip)
    if not operator:
        raise HTTPException(status_code=409, detail="请先设置用户名")

    existing = (
        await mysql_db.execute(
            select(CaseTagPhrase).where(CaseTagPhrase.content == content)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    phrase = CaseTagPhrase(content=content, operator=operator)
    mysql_db.add(phrase)
    await mysql_db.commit()
    await mysql_db.refresh(phrase)
    return phrase


@router.delete("/{phrase_id}")
async def delete_phrase(
    phrase_id: int,
    mysql_db: AsyncSession = Depends(get_mysql_db),
    _current_user: User = Depends(get_current_user),
) -> dict:
    """删除一条快捷内容(共享清单,任何用户可删)。"""
    phrase = await mysql_db.get(CaseTagPhrase, phrase_id)
    if phrase is None:
        raise HTTPException(status_code=404, detail="快捷内容不存在")
    await mysql_db.delete(phrase)
    await mysql_db.commit()
    return {"ok": True}
