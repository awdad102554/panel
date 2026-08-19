import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator


# 人工「审核结果」——「不同意」的 8 个固定理由(单选)。
# 仅「请补正」「其他」需要补填具体信息。
REJECT_REASONS: tuple[str, ...] = (
    "您的预申请不属于劳动人事争议仲裁委受案范围",
    "您的预申请中仲裁请求和事实理由不明确",
    "您的预申请中被申请人不明确（或被申请人信息有误）",
    "您的预申请不属于本委管辖范围",
    "您的预申请事项已经受理，案件正在审理中，请勿重复提交",
    "您的预申请事项已经由仲裁机构处理完毕，请勿重复提交",
    "请补正",
    "其他",
)
REJECT_REASONS_NEED_DETAIL: frozenset[str] = frozenset({"请补正", "其他"})


class PendingReserveOut(BaseModel):
    """待审核预约案件(来自内网同步快照,status=0)。"""

    external_case_id: str
    reserve_row_id: int
    applicant: str
    respondent: str
    reserve_at: str | None = None
    case_reason: str | None = None
    reserve_time_limit: str | None = None
    has_review: bool = False
    latest_conclusion: str | None = None
    submitted: bool = False  # 是否已提交内网审核(不可重复提交)


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
    decision: str | None = None  # AI 预测:同意/不同意
    reject_reason: str | None = None  # AI 预测:不同意理由(8 选 1)
    reject_detail: str | None = None  # AI 预测:请补正/其他 的补充说明
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


class ReserveReviewDecisionCreate(BaseModel):
    """人工审核结果提交:同意 / 不同意(不同意须给理由,「请补正」「其他」须给补充说明)。"""

    decision: Literal["同意", "不同意"]
    reject_reason: str | None = None
    reject_detail: str | None = None

    @model_validator(mode="after")
    def _validate_decision(self):
        # 跨字段校验必须用 model_validator:field_validator 在可选字段缺省时不会触发。
        if self.decision == "不同意":
            if not self.reject_reason:
                raise ValueError("不同意时必须选择理由")
            if self.reject_reason not in REJECT_REASONS:
                raise ValueError("不支持的「不同意」理由")
            if self.reject_reason in REJECT_REASONS_NEED_DETAIL and not (self.reject_detail or "").strip():
                raise ValueError("该理由需填写具体信息")
        else:
            # 同意时清空理由与补充说明,避免残留脏数据。
            self.reject_reason = None
            self.reject_detail = None
        return self


class ReserveReviewDecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_case_id: str
    reserve_row_id: int
    applicant: str
    respondent: str
    case_reason: str | None = None
    decision: str
    reject_reason: str | None = None
    reject_detail: str | None = None
    created_at: datetime
    created_by: str
    submitted_at: datetime | None = None
    submitted_by: str | None = None
    internal_status: int | None = None
    internal_reason: str | None = None
