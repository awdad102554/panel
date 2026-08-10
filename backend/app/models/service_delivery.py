import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ServiceMethod(str, enum.Enum):
    PICKUP = "pickup"  # 现场领取
    MAIL = "mail"  # 邮寄送达


class ServiceStatus(str, enum.Enum):
    PENDING = "pending"  # 待送达
    NOTIFIED = "notified"  # 已通知
    DELIVERED = "delivered"  # 已送达


class ServiceDelivery(Base):
    """通知送达记录，对应 03 文档阶段十 / 06 文档页面七。"""

    __tablename__ = "service_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id"), index=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True
    )
    method: Mapped[ServiceMethod] = mapped_column(String(16))
    status: Mapped[ServiceStatus] = mapped_column(String(16), default=ServiceStatus.PENDING)
    tracking_no: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 快递单号
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
