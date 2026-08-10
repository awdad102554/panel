import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.timeline import CaseTimelineEvent


async def add_timeline_event(
    db: AsyncSession,
    case_id: uuid.UUID,
    event_type: str,
    summary: str,
    created_by: str | None = None,
) -> CaseTimelineEvent:
    """统一时间线写入入口，对应 06 文档页面五：所有业务动作均通过此函数落时间线，
    避免各模块各自实现记录逻辑导致格式不一致。
    """

    event = CaseTimelineEvent(
        case_id=case_id,
        event_type=event_type,
        summary=summary,
        created_by=created_by,
    )
    db.add(event)
    await db.flush()
    return event
