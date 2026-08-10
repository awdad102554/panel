import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.service_delivery import ServiceDelivery, ServiceMethod, ServiceStatus
from app.services.timeline_service import add_timeline_event


async def create_service_delivery(
    db: AsyncSession,
    case_id: uuid.UUID,
    method: ServiceMethod,
    document_id: uuid.UUID | None = None,
) -> ServiceDelivery:
    delivery = ServiceDelivery(case_id=case_id, method=method, document_id=document_id)
    db.add(delivery)
    await db.flush()
    await add_timeline_event(
        db,
        case_id=case_id,
        event_type="service_delivery",
        summary=f"发起送达（方式：{method.value}）",
    )
    return delivery


async def mark_delivered(db: AsyncSession, delivery: ServiceDelivery, tracking_no: str | None = None) -> ServiceDelivery:
    delivery.status = ServiceStatus.DELIVERED
    if tracking_no:
        delivery.tracking_no = tracking_no
    await add_timeline_event(
        db,
        case_id=delivery.case_id,
        event_type="service_delivery",
        summary="送达完成",
    )
    return delivery


async def list_case_deliveries(db: AsyncSession, case_id: uuid.UUID) -> list[ServiceDelivery]:
    stmt = select(ServiceDelivery).where(ServiceDelivery.case_id == case_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())
