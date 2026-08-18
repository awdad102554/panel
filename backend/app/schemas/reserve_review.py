import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class PendingReserveOut(BaseModel):
    """待审核预约案件(来自内网同步快照,status=0)。"""

    external_case_id: str
    reserve_row_id: int
    applicant: str
    respondent: str
    reserve_at: str | None = None
    case_reason: str | None = None
    reserve_time_limit: str | None = None


class ReserveReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_case_id: str
    reserve_row_id: int
    applicant: str
    respondent: str
    case_reason: str | None = None
    conclusion: str
    reason: str
    issues: list[Any] = []
    missing_materials: list[Any] = []
    rule_refs: list[Any] = []
    checks: list[Any] = []
    model_name: str | None = None
    case_snapshot: dict[str, Any] = {}
    raw_result: dict[str, Any] = {}
    created_at: datetime
    created_by: str


class ReserveCaseDetailOut(BaseModel):
    """预约案件完整信息(实时拉内网详情后结构化),供前端「查看案件」弹窗。"""

    external_case_id: str
    reserve_row_id: int
    applicant: str
    respondent: str
    case_reason: str | None = None
    reserve_at: str | None = None
    reserve_time_limit: str | None = None
    detail: dict[str, Any] = {}
