import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.case import Case, CaseStatus


async def get_case_by_id(db: AsyncSession, case_id: uuid.UUID) -> Case | None:
    stmt = select(Case).where(Case.id == case_id).options(selectinload(Case.parties))
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_cases(
    db: AsyncSession,
    status: CaseStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Case]:
    stmt = (
        select(Case)
        .options(selectinload(Case.parties))
        .order_by(Case.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if status is not None:
        stmt = stmt.where(Case.status == status)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create_case(db: AsyncSession, claims: str | None = None) -> Case:
    case = Case(claims=claims, status=CaseStatus.RECEIVED, parties=[])
    db.add(case)
    await db.flush()
    return case
