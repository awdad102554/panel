import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utcnow


class CaseStatus(str, enum.Enum):
    """案件生命周期状态，对应 03 仲裁业务流程 / 07 技术沟通说明 第八章状态机。

    合法迁移顺序由 app.services.case_lifecycle.ALLOWED_TRANSITIONS 定义，
    本枚举只声明状态本身，不包含流转规则。
    """

    RECEIVED = "received"  # 收件
    PRE_REVIEW = "pre_review"  # AI 收件预审
    MEDIATION = "mediation"  # 案前调解（可选）
    FILED = "filed"  # 正式立案
    PRE_HEARING = "pre_hearing"  # 庭前准备
    HEARING = "hearing"  # 开庭
    POST_HEARING = "post_hearing"  # 庭后处理
    DECISION = "decision"  # 裁决书生成
    SERVICE = "service"  # 通知与送达
    ARCHIVED = "archived"  # 归档


class PartyType(str, enum.Enum):
    APPLICANT = "applicant"  # 申请人
    RESPONDENT = "respondent"  # 被申请人


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_no: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    status: Mapped[CaseStatus] = mapped_column(String(32), default=CaseStatus.RECEIVED, index=True)

    claims: Mapped[str | None] = mapped_column(Text, nullable=True)  # 仲裁请求
    risk_level: Mapped[str | None] = mapped_column(String(16), nullable=True)  # low/medium/high

    filed_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # 立案日期
    statute_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)  # 审限

    assigned_arbitrator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    parties: Mapped[list["Party"]] = relationship(back_populates="case", cascade="all, delete-orphan")


class Party(Base):
    __tablename__ = "parties"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id"))
    party_type: Mapped[PartyType] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(128))
    id_card_or_credit_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    case: Mapped["Case"] = relationship(back_populates="parties")
