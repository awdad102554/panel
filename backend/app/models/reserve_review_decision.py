import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReserveReviewDecision(Base):
    """人工「审核结果」留痕:工作人员对预约案件的最终审核决定(同意/不同意 + 理由)。

    与 ReserveAIReview(AI 初筛)区分:这是人工口径,后续将据此提交内网审批。
    追加式留痕,最新一条生效;本次仅本地落库,暂不提交内网(内网请求体待提供)。
    """

    __tablename__ = "reserve_review_decisions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_case_id: Mapped[str] = mapped_column(String(64), index=True)  # 内网 case_id(预约案件)
    reserve_row_id: Mapped[int] = mapped_column(Integer)  # 预约行内网 id(用于后续提交内网)
    applicant: Mapped[str] = mapped_column(String(128))
    respondent: Mapped[str] = mapped_column(String(256))
    case_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    decision: Mapped[str] = mapped_column(String(16))  # 同意 / 不同意
    reject_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)  # 不同意理由(8 选 1)
    reject_detail: Mapped[str | None] = mapped_column(Text, nullable=True)  # 请补正/其他 的补充说明
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    created_by: Mapped[str] = mapped_column(String(64), default="admin")
