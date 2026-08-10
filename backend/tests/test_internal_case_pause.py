"""internal_case_pause.paused_days_from_review_matter 与超审限判定的口径测试。"""

from datetime import date, datetime

from app.api.v1.dashboard import _is_over_statutory_limit
from app.models.internal_case import InternalCaseTracking
from app.services.internal_case_pause import paused_days_from_review_matter

TODAY = date(2026, 7, 31)


def _matter(step: str, approval_at: str | None, status: int = 3) -> dict:
    return {"apply_matter": step, "approval_at": approval_at, "status": status}


def test_pause_resume_pairing():
    """中止/恢复按审批通过时间配对;未审批通过的不计。"""
    matters = [
        _matter("中止审理", "2026-01-06 09:45:44"),
        _matter("恢复审理", "2026-03-10 09:18:27"),
        _matter("开庭安排", "2026-01-20 10:00:00"),  # 无关事项忽略
        _matter("中止审理", None),  # 未审批,忽略
    ]
    days = paused_days_from_review_matter(matters, date(2026, 4, 27))
    assert days == 62  # 62 天 23.8 小时,.days 截断为 62


def test_multiple_pauses_and_unmatched_pause_to_today():
    """多段中止累加;在办案件未恢复的中止计到今天(当天 0 点,按 .days 截断)。"""
    matters = [
        _matter("中止审理", "2026-01-01 09:00:00"),
        _matter("恢复审理", "2026-01-11 09:00:00"),  # 10 天
        _matter("中止审理", "2026-07-01 09:00:00"),  # 未恢复 → 到 7-31 00:00 为 29 天
    ]
    assert paused_days_from_review_matter(matters, None, today=TODAY) == 39


def test_consecutive_pauses_count_earliest():
    """连续两次中止(中间无恢复)按最早一次起算。"""
    matters = [
        _matter("中止审理", "2026-01-01 09:00:00"),
        _matter("中止审理", "2026-02-01 09:00:00"),
        _matter("恢复审理", "2026-02-11 09:00:00"),
    ]
    assert paused_days_from_review_matter(matters, date(2026, 3, 1)) == 41


def _row(
    handle_at: str,
    *,
    closed: bool,
    end_at: datetime | None,
    paused_days: int | None,
    extension_days: str = "0",
    clock_reset_at: date | None = None,
    paused_after_reset_days: int | None = None,
) -> InternalCaseTracking:
    row = InternalCaseTracking()
    row.stage = "handle"
    row.current_step = "已结案" if closed else "仲裁裁决中"
    row.raw_payload = {"handle_at": handle_at, "extension_days": extension_days}
    row.end_at = end_at
    row.paused_days = paused_days
    row.clock_reset_at = clock_reset_at
    row.paused_after_reset_days = paused_after_reset_days
    return row


def test_over_statutory_limit_open_case():
    # 立案 100 天前,无中止无延期 → 超 45 天审限
    row = _row("2026-04-22", closed=False, end_at=None, paused_days=0)
    assert _is_over_statutory_limit(row, TODAY) is True
    # 同样的案件,中止 60 天 → 实际经过 40 天,未超
    row = _row("2026-04-22", closed=False, end_at=None, paused_days=60)
    assert _is_over_statutory_limit(row, TODAY) is False
    # 批准延期 15 天(审限 60 天)→ 经过 100-60=40+20=... 100 天无中止,仍超 60
    row = _row("2026-04-22", closed=False, end_at=None, paused_days=0, extension_days="15")
    assert _is_over_statutory_limit(row, TODAY) is True
    # 延期 15 天 + 中止 45 天 → 经过 55 天 ≤ 60,未超
    row = _row("2026-04-22", closed=False, end_at=None, paused_days=45, extension_days="15")
    assert _is_over_statutory_limit(row, TODAY) is False


def test_over_statutory_limit_closed_case_uses_end_date():
    # 李上梅案口径:立案 2025-12-11,结案 2026-04-27(137 天),中止 62 天,延期 15 天
    # → 实际经过 75 天 > 60 天审限 → 超审限
    row = _row(
        "2025-12-11",
        closed=True,
        end_at=datetime(2026, 4, 26, 16, 0),
        paused_days=62,
        extension_days="15",
    )
    assert _is_over_statutory_limit(row, TODAY) is True
    # 若中止 80 天 → 经过 57 天 ≤ 60 → 未超
    row = _row(
        "2025-12-11",
        closed=True,
        end_at=datetime(2026, 4, 26, 16, 0),
        paused_days=80,
        extension_days="15",
    )
    assert _is_over_statutory_limit(row, TODAY) is False


def test_clock_reset_extraction():
    """变更仲裁请求/反申请/追加当事人触发审限重启,取最近一次;其他事项不触发。"""
    from app.services.internal_case_pause import clock_reset_from_review_matter

    matters = [
        _matter("变更仲裁请求", "2026-06-01 10:00:00"),
        _matter("变更仲裁庭组成人员", "2026-06-05 10:00:00"),  # 不重启
        _matter("仲裁反申请", "2026-06-10 10:00:00"),
        _matter("开庭安排", "2026-06-20 10:00:00"),  # 不重启
    ]
    assert clock_reset_from_review_matter(matters) == date(2026, 6, 10)
    assert clock_reset_from_review_matter([_matter("开庭安排", "2026-06-01 10:00:00")]) is None
    assert clock_reset_from_review_matter([]) is None


def test_over_limit_with_clock_reset_uses_reset_date():
    """2026-05-26 立案、2026-07-13 变更仲裁请求:从重启日起算 18 天,不超 45 天;
    若从立案日起算(66 天)则误判。"""
    row = _row(
        "2026-05-26",
        closed=False,
        end_at=None,
        paused_days=0,
        clock_reset_at=date(2026, 7, 13),
        paused_after_reset_days=0,
    )
    assert _is_over_statutory_limit(row, TODAY) is False


def test_over_limit_after_reset_only_deducts_post_reset_pause():
    """重启前的中止不扣:重启后经过 50 天、重启后中止 0 天 → 超 45;
    若错误地扣掉重启前的 30 天中止则变成 20 天漏判。"""
    row = _row(
        "2026-01-01",
        closed=False,
        end_at=None,
        paused_days=30,  # 全量中止(含重启前)
        clock_reset_at=date(2026, 6, 11),
        paused_after_reset_days=0,  # 重启后无中止
    )
    assert _is_over_statutory_limit(row, TODAY) is True
    # 重启后中止 10 天 → 经过 40 天,不超
    row = _row(
        "2026-01-01",
        closed=False,
        end_at=None,
        paused_days=40,
        clock_reset_at=date(2026, 6, 11),
        paused_after_reset_days=10,
    )
    assert _is_over_statutory_limit(row, TODAY) is False


def test_paused_days_since_filter():
    """since 过滤:重启前的中止区间不计,跨重启日的区间只计重启后部分。"""
    matters = [
        _matter("中止审理", "2026-01-01 09:00:00"),
        _matter("恢复审理", "2026-01-21 09:00:00"),  # 全在重启前 → 0
        _matter("中止审理", "2026-06-01 09:00:00"),
        _matter("恢复审理", "2026-06-21 09:00:00"),  # 跨重启日 6-11 → 只计 10 天
    ]
    reset = date(2026, 6, 11)
    assert paused_days_from_review_matter(matters, None, today=TODAY, since=reset) == 10
    # 不过滤则是 20 + 20 = 40
    assert paused_days_from_review_matter(matters, None, today=TODAY) == 40
