import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class ReserveAIReview(Base):
    """AI 预约审查留痕:每次审查的结论 JSON 与送入模型的案件摘要都落库。

    用途(见 docs/reserve-ai-review-prompt.md「留痕」建议):与最终人工决定对比,
    持续校准审查提示词。审查结论仅作初筛建议,不写回内网审批。
    """

    __tablename__ = "reserve_ai_reviews"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_case_id: Mapped[str] = mapped_column(String(64), index=True)  # 内网 case_id(预约案件)
    reserve_row_id: Mapped[int] = mapped_column(Integer)  # 预约行内网 id(用于拉详情)
    applicant: Mapped[str] = mapped_column(String(128))
    respondent: Mapped[str] = mapped_column(String(256))
    case_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    conclusion: Mapped[str] = mapped_column(String(32))  # 通过/补正/驳回/审查失败
    reason: Mapped[str] = mapped_column(Text, default="")
    issues: Mapped[list] = mapped_column(JSONB, default=list)
    missing_materials: Mapped[list] = mapped_column(JSONB, default=list)
    rule_refs: Mapped[list] = mapped_column(JSONB, default=list)
    checks: Mapped[list] = mapped_column(JSONB, default=list)  # 5 条规则逐项通过/不通过,供逐字段展示
    decision: Mapped[str | None] = mapped_column(String(16), nullable=True)  # AI 预测:同意/不同意
    reject_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)  # AI 预测:不同意理由(8 选 1)
    reject_detail: Mapped[str | None] = mapped_column(Text, nullable=True)  # AI 预测:请补正/其他 的补充说明
    model_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    case_snapshot: Mapped[dict] = mapped_column(JSONB)  # 送入 AI 的结构化摘要(供校准)
    raw_result: Mapped[dict] = mapped_column(JSONB)  # 模型原始输出(解析后的完整 JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str] = mapped_column(String(64), default="admin")
