import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.timeline import CaseTimelineEvent
from app.schemas.timeline import TimelineEventOut

router = APIRouter(prefix="/cases", tags=["timeline"])


@router.get("/{case_id}/timeline", response_model=list[TimelineEventOut])
async def get_case_timeline(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user),
) -> list[TimelineEventOut]:
    """案件时间线，对应 04 PRD 第六章 / 06 页面原型设计 页面五：自动按时间排序，无需分类。"""

    stmt = (
        select(CaseTimelineEvent)
        .where(CaseTimelineEvent.case_id == case_id)
        .order_by(CaseTimelineEvent.created_at.asc())
    )
    result = await db.execute(stmt)
    return [TimelineEventOut.model_validate(e) for e in result.scalars().all()]
