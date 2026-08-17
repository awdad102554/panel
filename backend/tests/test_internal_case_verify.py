"""internal_case_sync.verify_consistency 的环节容错测试(假客户端/假 DB,不触网)。

覆盖 2026-08-12 引入的逐环节容错:某环节抓取失败(200 返回 HTML / 非 200)时
记入 stage_errors 并跳过该环节比对——绝不能把"没拉到"当成"远端为空",
否则会把该环节全部案件误报为本地缺失。
"""

from __future__ import annotations

import httpx

from app.models.internal_case import InternalCaseTracking, InternalStage, SyncVerificationReport
from app.services.internal_case_sync import verify_consistency

RESERVE_PATH = "/v1/api/admin/arb/reserve"
RECEIVE_PATH = "/v1/api/admin/arb/receive"
HANDLE_PATH = "/v1/api/admin/arb/handle"


class FakeClient:
    """按路径返回预置响应;fail_on 里的路径返回 HTML(模拟上游 200 非 JSON)。"""

    def __init__(self, responses: dict[str, list[dict]], fail_on: set[str] | None = None):
        self._responses = responses
        self._fail_on = fail_on or set()

    async def get(self, path: str, *, params: dict | None = None, **_) -> httpx.Response:
        if path in self._fail_on:
            return httpx.Response(200, content=b"<html>bad gateway</html>")
        batch = self._responses.get(path, [])
        return httpx.Response(200, json={"data": {"data": batch, "totalNum": len(batch)}})


class _FakeResult:
    def __init__(self, rows: list):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class FakeDB:
    """只支持 verify_consistency 用到的 execute(select)/add。"""

    def __init__(self, rows: list):
        self._rows = rows
        self.added: list = []

    async def execute(self, stmt):
        return _FakeResult(self._rows)

    def add(self, obj):
        self.added.append(obj)


def _tracking(ext_id: str, stage: InternalStage) -> InternalCaseTracking:
    row = InternalCaseTracking()
    row.external_case_id = ext_id
    row.stage = stage.value
    row.current_step = "已结案" if stage is InternalStage.HANDLE else None
    row.case_no = None
    row.is_paused = False
    row.raw_payload = {"case_id": ext_id}
    return row


async def test_stage_fetch_failure_skipped_not_reported_missing():
    """handle 环节抓取失败(200 返回 HTML):跳过该环节,快照里的 handle 案件
    不得误报为本地缺失;receive 正常抓取的案件仍照常比对。"""
    snapshot = [_tracking("1", InternalStage.HANDLE)]
    client = FakeClient(
        {RECEIVE_PATH: [{"case_id": "2", "case_no": "收[2026]1号", "status": 0}]},
        fail_on={HANDLE_PATH},
    )
    db = FakeDB(snapshot)

    result = await verify_consistency(db, client)

    assert len(result["stage_errors"]) == 1
    assert result["stage_errors"][0].startswith("handle")
    # 失败环节的案件("1")不误报缺失;成功环节照常比对("2" 快照缺失)。
    assert result["missing_total"] == 1
    assert [m["case_no"] for m in result["missing_in_snapshot"]] == ["收[2026]1号"]
    assert result["checked"] == 1
    # 落库报告的 details 里也带 stage_errors,供事后排查。
    report = next(o for o in db.added if isinstance(o, SyncVerificationReport))
    assert report.details["stage_errors"] == result["stage_errors"]


async def test_all_stages_ok_no_stage_errors():
    """全部环节正常:stage_errors 为空,比对行为不变。"""
    snapshot = [_tracking("1", InternalStage.HANDLE)]
    client = FakeClient(
        {HANDLE_PATH: [{"case_id": "1", "current_step": "已结案", "end_way": "裁决"}]}
    )
    db = FakeDB(snapshot)

    result = await verify_consistency(db, client)

    assert result["stage_errors"] == []
    assert result["missing_total"] == 0
    assert result["checked"] == 1


async def test_reserve_status_change_reported():
    """reserve 环节加比内网 status:预约待审核被退回(0→2)环节/子状态都不变,
    只有 raw_payload.status 变化,必须报成 reserve_status 不一致(与 receive 同口径)。"""
    prev = _tracking("343842", InternalStage.RESERVE)
    prev.raw_payload = {"case_id": "343842", "status": 0}
    client = FakeClient(
        {RESERVE_PATH: [{"case_id": "343842", "status": 2, "overdue_days": 0}]}
    )
    db = FakeDB([prev])

    result = await verify_consistency(db, client)

    assert result["stage_errors"] == []
    assert result["mismatch_total"] == 1
    mismatch = result["field_mismatches"][0]
    assert mismatch["field"] == "reserve_status"
    assert mismatch["snapshot"] == 0
    assert mismatch["intranet"] == 2
