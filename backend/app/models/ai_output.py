import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AICapabilityType(str, enum.Enum):
    INTAKE_REVIEW = "intake_review"  # 收件预审
    CASE_UNDERSTANDING = "case_understanding"  # 案件理解
    LEGAL_ANALYSIS = "legal_analysis"  # 法律分析
    DECISION_DRAFT = "decision_draft"  # 裁决书生成


class AIOutput(Base):
    """所有 AI 能力的统一输出记录，对应 07 文档"AI 输出格式"与 05 文档"可追溯/可留痕"。

    result 统一使用 {summary, issues, risks, suggestions, references} 结构（见 app.ai.base.AIResult），
    confirmed_at 为空表示仲裁员尚未确认，非空则代表已进入正式业务数据。
    """

    __tablename__ = "ai_outputs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id"), index=True)
    capability: Mapped[AICapabilityType] = mapped_column(String(32))
    result: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
