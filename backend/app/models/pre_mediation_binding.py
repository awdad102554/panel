import uuid
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class PreMediationBinding(Base):
    """案前调解 → 立案 的一对一绑定关系。

    内网在立案时会为同一纠纷新建一条 handle 记录(新 case_id),原收件(receive)
    记录停留在 next_step=3(案前调解)永不关闭,造成"案前调解紧急"误报。绑定表
    把这类收件记录关联到它流转成的立案案件:
    - receive_external_case_id 唯一 —— 一个案前调解只能绑定一个立案案件;
    - 绑定后该案前调解从总览/监控/提醒里消失(相当于已进入下一阶段),记事
      (case_tags.subject_key=ext:{receive_id})转挂到 ext:{handle_id}。

    匹配在同步时按 申请人身份证号 + 被申请人名称 + 时间窗口(handle_at ≥ review_at)
    自动完成,见 services/pre_mediation_binding.py。
    """

    __tablename__ = "pre_mediation_bindings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 案前调解收件记录的内网 case_id(唯一:一个案前调解只能转一个立案案件)。
    receive_external_case_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # 绑定到的立案案件内网 case_id(handle 记录)。
    handle_external_case_id: Mapped[str] = mapped_column(String(64), index=True)
    # 立案案件的案号(如"明永劳人仲案字[2026]171号"),供人工核对;刚立案可能为空。
    handle_case_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
