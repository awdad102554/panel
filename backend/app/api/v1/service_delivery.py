import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.core.permissions import Action, require_permission
from app.db.session import get_db
from app.models.service_delivery import ServiceMethod, ServiceStatus
from app.services import service_delivery_service
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/cases", tags=["service-delivery"])


class ServiceDeliveryOut(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    method: ServiceMethod
    status: ServiceStatus
    tracking_no: str | None

    model_config = {"from_attributes": True}


class ServiceDeliveryCreate(BaseModel):
    method: ServiceMethod
    document_id: uuid.UUID | None = None


@router.get("/{case_id}/service-deliveries", response_model=list[ServiceDeliveryOut])
async def list_service_deliveries(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user),
) -> list[ServiceDeliveryOut]:
    """通知送达中心，对应 04 PRD 第九章 / 06 页面原型设计 页面七。"""

    deliveries = await service_delivery_service.list_case_deliveries(db, case_id)
    return [ServiceDeliveryOut.model_validate(d) for d in deliveries]


@router.post("/{case_id}/service-deliveries", response_model=ServiceDeliveryOut)
async def create_service_delivery(
    case_id: uuid.UUID,
    payload: ServiceDeliveryCreate,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_permission(Action.EDIT)),
) -> ServiceDeliveryOut:
    delivery = await service_delivery_service.create_service_delivery(
        db, case_id=case_id, method=payload.method, document_id=payload.document_id
    )
    await db.commit()
    await db.refresh(delivery)
    return ServiceDeliveryOut.model_validate(delivery)
