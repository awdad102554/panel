"""internal_case_sync._refetch_disappeared 的分支测试(假客户端,不触网)。

覆盖 2026-08-10 引入的日期定点探测与删除判定:
- receive 无案号案件日期窗口探测无记录 → 判定内网已删除,进 deleted_ids;
- receive 无案号案件日期窗口探测找到(已处理) → 更新进 merged;
- 探测请求失败 → 保留快照(不进 merged、不删),下轮重试;
- 有案号 receive 案件案号探测命中已处理 → 再探 handle(查到则按 handle 落)。
"""

from __future__ import annotations

import httpx
import pytest

from app.integrations.case_system.client import CaseSystemError
from app.models.internal_case import InternalCaseTracking, InternalStage
from app.services.internal_case_sync import _refetch_disappeared


class FakeClient:
    """按 (路径, 关键参数) 返回预置响应;responses 缺失时返回空列表。"""

    def __init__(self, responses: dict[tuple[str, str], list[dict]], fail_on: set[tuple[str, str]] | None = None):
        self._responses = responses
        self._fail_on = fail_on or set()
        self.calls: list[tuple[str, dict]] = []

    async def get(self, path: str, *, params: dict | None = None, **_) -> httpx.Response:
        params = params or {}
        self.calls.append((path, params))
        key = (path, self._fingerprint(params))
        if key in self._fail_on:
            return httpx.Response(500)
        batch = self._responses.get(key, [])
        body = {"data": {"data": batch, "totalNum": len(batch)}}
        return httpx.Response(200, json=body)

    @staticmethod
    def _fingerprint(params: dict) -> str:
        if "application_date" in params:
            return f"date={params['application_date']}"
        if "case_no" in params:
            return f"case_no={params['case_no']}"
        return ""


RECEIVE_PATH = "/v1/api/admin/arb/receive"
HANDLE_PATH = "/v1/api/admin/arb/handle"


def _tracking(
    ext_id: str,
    *,
    case_no: str | None,
    status: int = 0,
    application_at: str = "2026-08-06 10:00:00",
) -> InternalCaseTracking:
    row = InternalCaseTracking()
    row.external_case_id = ext_id
    row.stage = InternalStage.RECEIVE.value
    row.current_step = None
    row.case_no = case_no
    row.is_paused = False
    row.raw_payload = {
        "case_id": ext_id,
        "status": status,
        "application_at": application_at,
    }
    return row


@pytest.mark.asyncio
async def test_no_case_no_deleted_in_intranet():
    """无案号案件:案号探测无效,日期窗口(±1天)探测无记录 → 判定删除。"""
    prev = _tracking("341415", case_no="09598c9a669f1421f5087adbc11015cf")
    client = FakeClient({})  # 所有请求都返回空
    merged: dict[str, dict] = {}

    refetched, deleted = await _refetch_disappeared(client, {"341415": prev}, merged, reserve_complete=True)

    assert refetched == 0
    assert deleted == ["341415"]
    assert merged == {}
    # 日期探测发了 3 次(当天/前一天/后一天),不带 case_no 参数。
    date_calls = [p for path, p in client.calls if "application_date" in p]
    assert {p["application_date"] for p in date_calls} == {"2026-08-06", "2026-08-05", "2026-08-07"}
    assert not any("case_no" in p for _, p in client.calls if "application_date" in p)


@pytest.mark.asyncio
async def test_no_case_no_processed_found_by_date():
    """无案号案件:日期探测找到(已退回 status=2) → 更新进 merged,不删。"""
    prev = _tracking("341421", case_no="ac9ee87608f6dbd42dc6013e77e74e79")
    found = {
        "case_id": "341421",
        "case_no": "ac9ee87608f6dbd42dc6013e77e74e79",
        "status": 2,
        "application_at": "2026-08-06 10:00:00",
        "receive_time_limit": "已结案",
    }
    client = FakeClient({(RECEIVE_PATH, "date=2026-08-06"): [found]})
    merged: dict[str, dict] = {}

    refetched, deleted = await _refetch_disappeared(client, {"341421": prev}, merged, reserve_complete=True)

    assert refetched == 1
    assert deleted == []
    # prev.stage 是 String 列读回的 str,_map_record 原样保留,故用 == 而非 is。
    assert merged["341421"]["stage"] == InternalStage.RECEIVE
    assert merged["341421"]["raw_payload"]["status"] == 2


@pytest.mark.asyncio
async def test_probe_failure_keeps_snapshot():
    """日期探测请求失败 → 保留快照(不进 merged、不删),下轮重试。"""
    prev = _tracking("341415", case_no="hash-no-case-no")
    client = FakeClient({}, fail_on={(RECEIVE_PATH, "date=2026-08-06")})
    merged: dict[str, dict] = {}

    refetched, deleted = await _refetch_disappeared(client, {"341415": prev}, merged, reserve_complete=True)

    assert refetched == 0
    assert deleted == []
    assert merged == {}


@pytest.mark.asyncio
async def test_case_no_processed_then_probe_handle():
    """有案号案件:案号探测命中已处理(status=1) → 再探 handle,查到则按 handle 落。"""
    prev = _tracking("500", case_no="明永劳人仲案字[2026]100号")
    receive_hit = {
        "case_id": "500",
        "case_no": "明永劳人仲案字[2026]100号",
        "status": 1,
        "application_at": "2026-08-06 10:00:00",
    }
    handle_hit = {
        "case_id": "500",
        "case_no": "明永劳人仲案字[2026]100号",
        "current_step": "已结案",
        "end_at": "2026-08-09 15:00:00",
        "end_way": "裁决",
    }
    client = FakeClient({
        (RECEIVE_PATH, "case_no=[2026]100"): [receive_hit],
        (HANDLE_PATH, "case_no=[2026]100"): [handle_hit],
    })
    merged: dict[str, dict] = {}

    refetched, deleted = await _refetch_disappeared(client, {"500": prev}, merged, reserve_complete=True)

    assert refetched == 1
    assert deleted == []
    assert merged["500"]["stage"] is InternalStage.HANDLE
    assert merged["500"]["current_step"] == "已结案"
    assert merged["500"]["end_way"] == "裁决"


@pytest.mark.asyncio
async def test_case_no_processed_handle_probe_failure_keeps_snapshot():
    """有案号案件:案号命中已处理但 handle 探测失败 → 保留快照下轮重试(防冻结)。"""
    prev = _tracking("501", case_no="明永劳人仲案字[2026]101号")
    receive_hit = {
        "case_id": "501",
        "case_no": "明永劳人仲案字[2026]101号",
        "status": 1,
        "application_at": "2026-08-06 10:00:00",
    }
    client = FakeClient(
        {(RECEIVE_PATH, "case_no=[2026]101"): [receive_hit]},
        fail_on={(HANDLE_PATH, "case_no=[2026]101")},
    )
    merged: dict[str, dict] = {}

    refetched, deleted = await _refetch_disappeared(client, {"501": prev}, merged, reserve_complete=True)

    assert refetched == 0
    assert deleted == []
    assert merged == {}


@pytest.mark.asyncio
async def test_no_payload_date_keeps_snapshot():
    """快照缺申请日期(无法探测) → 保留原值,绝不能误判删除。"""
    prev = _tracking("900", case_no="hash-no-date", application_at="")  # 无有效日期
    prev.raw_payload = {"case_id": "900", "status": 0}  # 三个日期键都没有
    client = FakeClient({})
    merged: dict[str, dict] = {}

    refetched, deleted = await _refetch_disappeared(client, {"900": prev}, merged, reserve_complete=True)

    assert refetched == 0
    assert deleted == []
    assert merged == {}
    # 不应发出任何日期探测请求。
    assert not any("application_date" in p for _, p in client.calls)


@pytest.mark.asyncio
async def test_hash_case_no_approved_probes_handle_with_new_formal_case_no():
    """哈希案号案件保存后正式提交(status=1,获正式收字号):日期探测找到后,
    handle 探测必须用最新记录里的正式案号——用快照哈希案号会被正则短路,
    防冻结逻辑形同虚设(2026-08-10 复查发现的高危遗漏)。"""
    prev = _tracking("600", case_no="hash-draft-no")
    found = {
        "case_id": "600",
        "case_no": "明永劳人仲收[2026]300号",  # 正式提交后获得正式收字号
        "status": 1,
        "application_at": "2026-08-06 10:00:00",
    }
    handle_hit = {
        "case_id": "600",
        "case_no": "明永劳人仲案字[2026]300号",
        "current_step": "审理中",
        "closing_time_limit": "40",
    }
    client = FakeClient({
        (RECEIVE_PATH, "date=2026-08-06"): [found],
        (HANDLE_PATH, "case_no=[2026]300"): [handle_hit],
    })
    merged: dict[str, dict] = {}

    refetched, deleted = await _refetch_disappeared(client, {"600": prev}, merged, reserve_complete=True)

    assert refetched == 1
    assert deleted == []
    # handle 探测确实按正式案号发出(哈希案号会在正则处短路,不会发请求)。
    handle_calls = [p for path, p in client.calls if path == HANDLE_PATH]
    assert handle_calls and handle_calls[0].get("case_no") == "[2026]300"
    assert merged["600"]["stage"] == InternalStage.HANDLE
    assert merged["600"]["current_step"] == "审理中"


@pytest.mark.asyncio
async def test_date_probe_uses_receive_at_when_application_at_missing():
    """候选日期并集:application_at 缺失时回退 receive_at / created_at 探测。"""
    prev = _tracking("700", case_no="hash-no-app-date", application_at="")
    prev.raw_payload = {
        "case_id": "700",
        "status": 0,
        "receive_at": "2026-08-04 09:00:00",
    }
    found = {
        "case_id": "700",
        "case_no": "hash-no-app-date",
        "status": 0,
        "receive_at": "2026-08-04 09:00:00",
    }
    client = FakeClient({(RECEIVE_PATH, "date=2026-08-04"): [found]})
    merged: dict[str, dict] = {}

    refetched, deleted = await _refetch_disappeared(client, {"700": prev}, merged, reserve_complete=True)

    assert refetched == 1
    assert deleted == []
    probed_dates = {p["application_date"] for _, p in client.calls if "application_date" in p}
    assert "2026-08-04" in probed_dates


@pytest.mark.asyncio
async def test_case_no_not_found_falls_to_date_probe():
    """有案号案件:案号探测未查到(可能已删) → 回退日期探测,窗口内仍无 → 判定删除。"""
    prev = _tracking("502", case_no="明永劳人仲案字[2026]102号")
    client = FakeClient({})  # 案号、日期全部空
    merged: dict[str, dict] = {}

    refetched, deleted = await _refetch_disappeared(client, {"502": prev}, merged, reserve_complete=True)

    assert refetched == 0
    assert deleted == ["502"]
    assert any("case_no" in p for _, p in client.calls)  # 先试了案号
    assert any("application_date" in p for _, p in client.calls)  # 再退到日期探测


RESERVE_PATH = "/v1/api/admin/arb/reserve"


def _reserve_tracking(ext_id: str, status: int = 0) -> InternalCaseTracking:
    row = InternalCaseTracking()
    row.external_case_id = ext_id
    row.stage = InternalStage.RESERVE.value
    row.current_step = None
    row.case_no = ""  # 预约无正式案号
    row.is_paused = False
    row.raw_payload = {"case_id": ext_id, "status": status}
    return row


@pytest.mark.asyncio
async def test_reserve_disappeared_deleted_when_fetch_complete():
    """reserve 全量拉取成功时,消失的预约快照(已审核转收件/内网删除)直接删除,
    不发任何探测请求(预约无案号可探)。"""
    prev = _reserve_tracking("343842")
    client = FakeClient({})
    merged: dict[str, dict] = {}

    refetched, deleted = await _refetch_disappeared(
        client, {"343842": prev}, merged, reserve_complete=True
    )

    assert refetched == 0
    assert deleted == ["343842"]
    assert merged == {}
    assert client.calls == []


@pytest.mark.asyncio
async def test_reserve_disappeared_kept_when_fetch_failed():
    """reserve 拉取失败(reserve_complete=False):消失的预约快照保留原值下轮重试,
    不能把"没拉到"误判成"已离开"。"""
    prev = _reserve_tracking("343842")
    client = FakeClient({})
    merged: dict[str, dict] = {}

    refetched, deleted = await _refetch_disappeared(
        client, {"343842": prev}, merged, reserve_complete=False
    )

    assert refetched == 0
    assert deleted == []
    assert merged == {}
    assert client.calls == []


def test_map_record_reserve_parses_native_time_limit():
    """reserve 优先解析原生 reserve_time_limit 文案(与 receive_time_limit 同格式,
    负数=超期);解析不到退回 overdue_days 兜底。"""
    from app.services.internal_case_sync import _map_record

    raw = {"case_id": 1, "status": 0, "reserve_time_limit": "2天", "overdue_days": 0}
    assert _map_record(InternalStage.RESERVE, raw)["native_remaining_days"] == 2

    raw = {"case_id": 1, "status": 0, "reserve_time_limit": "超期3天", "overdue_days": 3}
    assert _map_record(InternalStage.RESERVE, raw)["native_remaining_days"] == -3

    # 无 reserve_time_limit 时 overdue_days>0 兜底(负数=超期)。
    raw = {"case_id": 1, "status": 0, "overdue_days": 5}
    assert _map_record(InternalStage.RESERVE, raw)["native_remaining_days"] == -5

    raw = {"case_id": 1, "status": 2, "overdue_days": 0}
    assert _map_record(InternalStage.RESERVE, raw)["native_remaining_days"] is None


def test_map_record_accepts_string_stage():
    """回归:快照列 stage 是 String,读回为 str;_map_record 必须能处理,
    否则补拉(在办→结案翻转)时 current_step/end_way 静默变 None(2026-08-12 全量校验发现)。"""
    from app.services.internal_case_sync import _map_record

    raw = {
        "case_id": 1,
        "case_no": "明永劳人仲案字[2026]213号",
        "current_step": "已结案",
        "end_way": "调解",
        "end_at": "2026-08-12",
    }
    by_enum = _map_record(InternalStage.HANDLE, raw)
    by_str = _map_record("handle", raw)  # type: ignore[arg-type] 快照读回即字符串
    assert by_str["current_step"] == by_enum["current_step"] == "已结案"
    assert by_str["end_way"] == by_enum["end_way"] == "调解"
