"""案件标签路由:按案件线程(subject_key)追加标签,只增不改,与 InfoWeb 共用。

subject_key 见 services/case_tags.py:ext:{内网 case_id} / virt:{预登记 id}。
时间(created_at)/设备IP(client_ip)/环节(stage)/操作人(operator=IP→用户名)服务端自动落,内容用户填。
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, field_serializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.mysql import get_mysql_db
from app.db.session import get_db
from app.models.case_tag import CaseTag
from app.models.user import User
from app.services.case_tags import get_username_by_ip, resolve_subject_stage

router = APIRouter(prefix="/case-tags", tags=["case-tags"])

MAX_CONTENT_LEN = 2000


def _extract_client_ip(forwarded: str | None, real: str | None, client_host: str | None) -> str:
    """取真实客户端 IP。

    nginx 用 $proxy_add_x_forwarded_for(追加式),客户端可自带 X-Forwarded-For 头伪造
    首跳;X-Real-IP 恒为 nginx 覆盖的 $remote_addr,不可伪造,故优先取它。
    无 X-Real-IP 时取 XFF 末跳(同样是 nginx 追加的 $remote_addr),而非可伪造的首跳。
    """
    if real:
        return real.strip()
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return client_host or ""


def _client_ip(request: Request) -> str:
    return _extract_client_ip(
        request.headers.get("x-forwarded-for"),
        request.headers.get("x-real-ip"),
        request.client.host if request.client else None,
    )


class TagCreate(BaseModel):
    content: str


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    subject_key: str
    content: str
    stage: str
    operator: str
    client_ip: str
    created_at: datetime

    @field_serializer("created_at")
    def _ser_created_at(self, v: datetime) -> datetime:
        # MySQL DATETIME 读回为 naive(UTC 墙钟),补 UTC 时区,前端 new Date 才能转本地。
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v


@router.get("/{subject_key}", response_model=list[TagOut])
async def list_tags(
    subject_key: str,
    mysql_db: AsyncSession = Depends(get_mysql_db),
    _current_user: User = Depends(get_current_user),
) -> list[TagOut]:
    """列出某案件线程的全部标签(时间正序,像时间线);案件已删时标签仍可读。"""
    stmt = (
        select(CaseTag)
        .where(CaseTag.subject_key == subject_key)
        .order_by(CaseTag.created_at.asc(), CaseTag.id.asc())
    )
    return list((await mysql_db.execute(stmt)).scalars().all())


@router.post("/{subject_key}", response_model=TagOut)
async def create_tag(
    subject_key: str,
    payload: TagCreate,
    request: Request,
    pg_db: AsyncSession = Depends(get_db),
    mysql_db: AsyncSession = Depends(get_mysql_db),
    _current_user: User = Depends(get_current_user),
) -> TagOut:
    """新增一条标签:内容用户填,时间/IP/环节/操作人服务端自动落。

    环节从 PG 快照解析;操作人由客户端 IP 查 user_ip 绑定而来,未绑定则要求先设置用户名。
    """
    content = (payload.content or "").strip()
    if not content:
        raise HTTPException(status_code=422, detail="标签内容不能为空")
    if len(content) > MAX_CONTENT_LEN:
        raise HTTPException(status_code=422, detail=f"标签内容过长(最多 {MAX_CONTENT_LEN} 字)")

    try:
        stage = await resolve_subject_stage(pg_db, subject_key)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    ip = _client_ip(request)
    operator = await get_username_by_ip(mysql_db, ip)
    if not operator:
        raise HTTPException(status_code=409, detail="请先设置用户名")

    tag = CaseTag(
        subject_key=subject_key,
        content=content,
        stage=stage,
        operator=operator,
        client_ip=ip,
    )
    mysql_db.add(tag)
    await mysql_db.commit()
    await mysql_db.refresh(tag)
    return tag
