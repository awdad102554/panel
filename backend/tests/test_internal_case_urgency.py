"""internal_case_urgency.compute_urgency 的口径测试(纯函数,不依赖数据库)。

构造内存中的 InternalCaseTracking/Override 对象直接调用,
覆盖已确认的业务口径:人工覆盖优先、中止单独标记、结案即终态、
reserve 原生超期信号、receive 待审核超期红色提醒、未识别子状态优雅降级。
"""

from datetime import date, datetime, timedelta

from app.core.config import Settings
from app.models.internal_case import (
    CaseTimeLimitOverride,
    InternalCaseTracking,
    InternalStage,
)
from app.services.internal_case_urgency import compute_urgency

TODAY = date.today()
SETTINGS = Settings(
    case_urgency_reserve_days=5,
    case_urgency_receive_days=5,
    case_urgency_soon_days=3,
    case_urgency_urgent_days=1,
    case_urgency_paused_alert_days=15,
)


def make_row(
    stage: InternalStage,
    current_step: str | None = None,
    is_paused: bool = False,
    native_remaining_days: int | None = None,
    days_since_phase: int = 0,
    raw_payload: dict | None = None,
) -> InternalCaseTracking:
    row = InternalCaseTracking()
    row.external_case_id = "test-1"
    row.stage = stage
    row.current_step = current_step
    row.is_paused = is_paused
    row.native_remaining_days = native_remaining_days
    row.phase_entered_at = datetime.utcnow() - timedelta(days=days_since_phase)
    row.end_at = None
    row.raw_payload = raw_payload or {}
    return row


def test_override_takes_priority_over_native_signal():
    row = make_row(InternalStage.HANDLE, native_remaining_days=30)
    override = CaseTimeLimitOverride(
        external_case_id="test-1",
        deadline_override=TODAY - timedelta(days=2),
        created_by="tester",
    )
    result = compute_urgency(row, override, SETTINGS)
    assert result.urgency == "overdue"
    assert result.days_remaining == -2
    assert result.source == "override"


def test_handle_native_remaining_days():
    row = make_row(InternalStage.HANDLE, native_remaining_days=-1)
    assert compute_urgency(row, None, SETTINGS).urgency == "overdue"

    row = make_row(InternalStage.HANDLE, native_remaining_days=2)
    result = compute_urgency(row, None, SETTINGS)
    assert result.urgency == "soon"
    assert result.source == "native"

    row = make_row(InternalStage.HANDLE, native_remaining_days=30)
    assert compute_urgency(row, None, SETTINGS).urgency == "normal"


def test_handle_closed_is_terminal():
    """已结案即终态(2026-07-30 口径:取消结案后送达跟踪),不论结案多久都按 closed 隐藏。"""
    row = make_row(InternalStage.HANDLE, current_step="已结案")
    assert compute_urgency(row, None, SETTINGS).urgency == "closed"

    row = make_row(InternalStage.HANDLE, current_step="已归档", days_since_phase=300)
    assert compute_urgency(row, None, SETTINGS).urgency == "closed"


def test_handle_paused_not_counted_as_overdue():
    row = make_row(InternalStage.HANDLE, current_step="审理中止", is_paused=True, days_since_phase=3)
    result = compute_urgency(row, None, SETTINGS)
    assert result.urgency == "paused"

    row = make_row(InternalStage.HANDLE, current_step="审理中止", is_paused=True, days_since_phase=20)
    result = compute_urgency(row, None, SETTINGS)
    assert result.urgency == "paused_overdue"


def test_handle_rework_steps_are_overdue():
    """结案审核/审批、处理文书审批未通过=返工,按最高优先级 overdue 提醒。"""
    for step in ("结案审核未通过", "结案审批未通过", "处理文书审批未通过"):
        row = make_row(InternalStage.HANDLE, current_step=step, native_remaining_days=30)
        result = compute_urgency(row, None, SETTINGS)
        assert result.urgency == "overdue"
        assert result.source == "status"


def test_handle_mediation_alerts_after_threshold():
    """组织调解无原生时限,进入调解环节超过 case_mediation_alert_days(默认30)提醒。"""
    row = make_row(InternalStage.HANDLE, current_step="组织调解", days_since_phase=10)
    assert compute_urgency(row, None, SETTINGS).urgency == "normal"

    row = make_row(InternalStage.HANDLE, current_step="组织调解", days_since_phase=40)
    assert compute_urgency(row, None, SETTINGS).urgency == "soon"


def test_handle_unrecognized_step_falls_back_gracefully():
    """current_step 枚举不封闭:未识别的子状态按普通在办处理,不报错。"""
    row = make_row(InternalStage.HANDLE, current_step="某种新子状态", native_remaining_days=10)
    result = compute_urgency(row, None, SETTINGS)
    assert result.urgency == "normal"


def test_reserve_rejected_is_not_overdue():
    """reserve.status 2/4(审核/现场确认不通过)是退回申请人补正,单列 rejected,不算超期。"""
    for s in (2, 4):
        row = make_row(InternalStage.RESERVE, days_since_phase=100, raw_payload={"status": s})
        result = compute_urgency(row, None, SETTINGS)
        assert result.urgency == "rejected"
        assert result.source == "status"


def test_reserve_approved_is_not_alarmed():
    """reserve.status 1/3(审核/现场确认通过):reserve 环节工作已完成,不告警。"""
    for s in (1, 3):
        row = make_row(InternalStage.RESERVE, days_since_phase=100, raw_payload={"status": s})
        result = compute_urgency(row, None, SETTINGS)
        assert result.urgency == "normal"


def test_reserve_pending_review_is_monitored():
    """reserve.status 0(待审核)是工作人员待办;时限 5 天:刚进正常,剩 2 天临近,超时超期。"""
    row = make_row(InternalStage.RESERVE, days_since_phase=1, raw_payload={"status": 0})
    assert compute_urgency(row, None, SETTINGS).urgency == "normal"

    row = make_row(InternalStage.RESERVE, days_since_phase=3, raw_payload={"status": 0})
    assert compute_urgency(row, None, SETTINGS).urgency == "soon"  # 剩 2 天

    row = make_row(InternalStage.RESERVE, days_since_phase=10, raw_payload={"status": 0})
    assert compute_urgency(row, None, SETTINGS).urgency == "overdue"


def test_reserve_native_overdue_signal():
    row = make_row(InternalStage.RESERVE, native_remaining_days=-4)
    result = compute_urgency(row, None, SETTINGS)
    assert result.urgency == "overdue"
    assert result.source == "native"


def test_reserve_elapsed_estimate():
    row = make_row(InternalStage.RESERVE, days_since_phase=1)
    # 时限 5 天、过 1 天剩 4 天 > 临近阈值 3 → 正常(环节时限只定超期点,不定警告起点)
    assert compute_urgency(row, None, SETTINGS).urgency == "normal"

    row = make_row(InternalStage.RESERVE, days_since_phase=10)
    assert compute_urgency(row, None, SETTINGS).urgency == "overdue"


def test_receive_elapsed_may_overdue():
    """receive 待审核:刚进正常(剩 4>3),剩 2 天临近,剩 1 天紧急,超时超期。"""
    row = make_row(InternalStage.RECEIVE, days_since_phase=1)
    assert compute_urgency(row, None, SETTINGS).urgency == "normal"

    row = make_row(InternalStage.RECEIVE, days_since_phase=3)
    assert compute_urgency(row, None, SETTINGS).urgency == "soon"

    row = make_row(InternalStage.RECEIVE, days_since_phase=4)
    assert compute_urgency(row, None, SETTINGS).urgency == "urgent"

    row = make_row(InternalStage.RECEIVE, days_since_phase=100)
    assert compute_urgency(row, None, SETTINGS).urgency == "overdue"


def test_urgent_tier_between_overdue_and_soon():
    """剩余天数 ≤ 紧急阈值(测试 SETTINGS 为 1) 升级 urgent;<0 为 overdue;≤临近阈值(3) 为 soon。"""
    row = make_row(InternalStage.HANDLE, native_remaining_days=1)
    assert compute_urgency(row, None, SETTINGS).urgency == "urgent"

    row = make_row(InternalStage.HANDLE, native_remaining_days=2)
    assert compute_urgency(row, None, SETTINGS).urgency == "soon"

    row = make_row(InternalStage.HANDLE, native_remaining_days=3)
    assert compute_urgency(row, None, SETTINGS).urgency == "soon"

    row = make_row(InternalStage.HANDLE, native_remaining_days=-1)
    assert compute_urgency(row, None, SETTINGS).urgency == "overdue"


def test_handle_fallback_without_native_limit():
    """无 closing_time_limit 的在办案件按进入天数兜底(估算时限=临近阈值)。"""
    row = make_row(InternalStage.HANDLE, native_remaining_days=None, days_since_phase=0)
    assert compute_urgency(row, None, SETTINGS).urgency == "soon"  # 剩=阈值,即临近

    row = make_row(InternalStage.HANDLE, native_remaining_days=None, days_since_phase=10)
    assert compute_urgency(row, None, SETTINGS).urgency == "overdue"
