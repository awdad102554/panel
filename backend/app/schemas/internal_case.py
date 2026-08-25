from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.models.internal_case import InternalStage

InternalCaseUrgency = Literal[
    "overdue", "urgent", "soon", "normal", "paused", "paused_overdue", "closed", "rejected"
]


class InternalCaseOut(BaseModel):
    """监控列表条目:同步快照字段 + 实时计算的紧急度。"""

    model_config = ConfigDict(from_attributes=True)

    external_case_id: str
    stage: InternalStage
    current_step: str | None = None
    case_no: str | None = None
    applicant: str | None = None  # 申请人姓名(取自 raw_payload)
    respondent: str | None = None  # 被申请人名称(取自 raw_payload)
    is_paused: bool = False
    native_remaining_days: int | None = None
    extension_days: int = 0  # 已批准的延期天数(已并入 native_remaining_days)
    end_at: datetime | None = None
    end_way: str | None = None
    phase_entered_at: datetime
    # 进入当前子状态的时间(仅案前调解=审核通过 review_at;其余环节为 None)。
    # 明细列表用它展示"进入状态时间",替代无意义的"剩余天数/已超期"口径(2026-08-24)。
    state_entered_at: datetime | None = None
    last_synced_at: datetime

    # 计算字段
    urgency: InternalCaseUrgency
    days_remaining: int | None = None
    urgency_source: str
    # 关联的人工状态
    has_override: bool = False
    override_deadline: date | None = None


class InternalCaseDetailOut(InternalCaseOut):
    """详情:附带内网原始 payload(含嵌套 cases 详情)与人工记录备注。"""

    raw_payload: dict
    override_note: str | None = None


class OverrideRequest(BaseModel):
    deadline_override: date
    note: str | None = None


class SyncResultOut(BaseModel):
    counts: dict[str, int]
