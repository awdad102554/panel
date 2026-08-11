"""dashboard._virtual_case_out 预登记案件紧急度分档测试。

口径(2026-08-11):按登记后的自然日数分档,阈值走时限设置
virtual_case_soon_days(默认 30)/ virtual_case_urgent_days(默认 60)。
"""

from datetime import date, datetime, timedelta, timezone

from app.api.v1.dashboard import _virtual_case_out
from app.core.config import get_settings
from app.db.virtual import VirtualCase

_TODAY = date(2026, 8, 11)


def _virtual_case(days_ago: int) -> VirtualCase:
    row = VirtualCase()
    row.id = "v-1"
    row.receipt_number = "预登[2026]001号"
    row.created_at = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc) - timedelta(days=days_ago)
    row.updated_at = row.created_at
    row.applicants = [{"name": "张三"}]
    row.respondents = [{"name": "某公司"}]
    return row


def test_within_soon_threshold_is_normal():
    out = _virtual_case_out(_virtual_case(29), get_settings(), _TODAY)
    assert out.urgency == "normal"
    assert out.days_remaining == 60 - 29


def test_over_soon_threshold_is_soon():
    out = _virtual_case_out(_virtual_case(30), get_settings(), _TODAY)
    assert out.urgency == "soon"
    assert out.days_remaining == 30


def test_over_urgent_threshold_is_urgent():
    out = _virtual_case_out(_virtual_case(60), get_settings(), _TODAY)
    assert out.urgency == "urgent"
    assert out.days_remaining == 0


def test_naive_created_at_treated_as_utc():
    """SQLite 读出的是 naive datetime(UTC 写入),按 UTC→CST 换算,不偏移。"""
    row = _virtual_case(30)
    row.created_at = row.created_at.replace(tzinfo=None)
    out = _virtual_case_out(row, get_settings(), _TODAY)
    assert out.urgency == "soon"
