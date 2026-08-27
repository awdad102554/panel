import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class DocumentType(str, enum.Enum):
    APPLICATION = "application"  # 仲裁申请书
    ANSWER = "answer"  # 答辩意见
    MEDIATION_AGREEMENT = "mediation_agreement"  # 调解书
    DECISION = "decision"  # 裁决书
    NOTICE = "notice"  # 通知书
    SERVICE_RECEIPT = "service_receipt"  # 送达回证


class Document(Base):
    """文书中心，对应 06 页面原型设计 页面六。支持 AI 生成 + 人工编辑 + 版本管理。"""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id"), index=True)
    doc_type: Mapped[DocumentType] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer, default=1)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_by_ai: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
