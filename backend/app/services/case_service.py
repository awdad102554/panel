import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case import Case, CaseStatus
from app.repositories import case_repository
from app.services.timeline_service import add_timeline_event


async def create_case(db: AsyncSession, claims: str | None, operator: str | None = None) -> Case:
    """案件池"收件"入口，对应 03 文档阶段一。"""

    case = await case_repository.create_case(db, claims=claims)
    await add_timeline_event(
        db,
        case_id=case.id,
        event_type="status_change",
        summary="案件收件",
        created_by=operator,
    )
    return case


async def get_case_pool(db: AsyncSession, status: CaseStatus | None = None) -> list[Case]:
    """案件池列表，对应 04 PRD 模块二。"""

    return await case_repository.list_cases(db, status=status)


async def get_case_workspace(db: AsyncSession, case_id: uuid.UUID) -> Case | None:
    """案件工作台唯一入口，对应 04 PRD 模块三。"""

    return await case_repository.get_case_by_id(db, case_id)
