from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case import Case, CaseStatus
from app.services.timeline_service import add_timeline_event

# 对应 03 仲裁业务流程"二、总体业务流程"与 07 技术沟通说明"八、状态管理"。
# 案前调解可选，因此 PRE_REVIEW 既可以流向 MEDIATION 也可以直接流向 FILED；
# 其余状态严格按业务顺序单向流转，不允许跳变或回退。
ALLOWED_TRANSITIONS: dict[CaseStatus, set[CaseStatus]] = {
    CaseStatus.RECEIVED: {CaseStatus.PRE_REVIEW},
    CaseStatus.PRE_REVIEW: {CaseStatus.MEDIATION, CaseStatus.FILED},
    CaseStatus.MEDIATION: {CaseStatus.FILED},
    CaseStatus.FILED: {CaseStatus.PRE_HEARING},
    CaseStatus.PRE_HEARING: {CaseStatus.HEARING},
    CaseStatus.HEARING: {CaseStatus.POST_HEARING},
    CaseStatus.POST_HEARING: {CaseStatus.DECISION},
    CaseStatus.DECISION: {CaseStatus.SERVICE},
    CaseStatus.SERVICE: {CaseStatus.ARCHIVED},
    CaseStatus.ARCHIVED: set(),
}


class InvalidTransitionError(Exception):
    pass


async def transition_case_status(
    db: AsyncSession,
    case: Case,
    target_status: CaseStatus,
    operator: str | None = None,
) -> Case:
    """校验并执行案件状态流转，同时落一条时间线记录，保证"可追溯、可记录、可审计"。"""

    allowed = ALLOWED_TRANSITIONS.get(case.status, set())
    if target_status not in allowed:
        raise InvalidTransitionError(
            f"案件当前状态为 {case.status}，不允许直接流转到 {target_status}"
        )

    previous_status = case.status
    case.status = target_status
    await add_timeline_event(
        db,
        case_id=case.id,
        event_type="status_change",
        summary=f"案件状态由 {previous_status.value} 流转至 {target_status.value}",
        created_by=operator,
    )
    return case
