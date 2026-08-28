"""submit_decision_to_internal 提交内网 preAudit 的单测(假客户端,不打内网)。"""

import asyncio

import pytest

from app.integrations.case_system.client import CaseSystemError
from app.services import reserve_decision_submit as mod
from app.services.reserve_decision_submit import submit_decision_to_internal


class _FakeResp:
    def __init__(self, status_code: int = 200, body=None, text: str = ""):
        self.status_code = status_code
        self._body = body
        self.text = text

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


class _FakeClient:
    def __init__(self, resp: _FakeResp):
        self.resp = resp
        self.called_method = None
        self.called_path = None
        self.called_payload = None

    async def put(self, path, json=None):
        # 内网 preAudit 路由只支持 PUT(POST 405),提交必须走 PUT。
        self.called_method = "PUT"
        self.called_path = path
        self.called_payload = json
        return self.resp


def _run(coro):
    return asyncio.run(coro)


def test_submit_posts_correct_path_and_payload(monkeypatch):
    fake = _FakeClient(_FakeResp(body={"code": 200, "data": {"ok": True}}))
    monkeypatch.setattr(mod, "get_case_system_client", lambda: fake)
    data = _run(submit_decision_to_internal(84177, "不同意", "其他", "1.缺工资月份；2.缺信用代码"))
    assert fake.called_method == "PUT"
    assert fake.called_path == "/v1/api/admin/arb/84177/reserve/preAudit"
    assert fake.called_payload == {"reason": "其他:1.缺工资月份；2.缺信用代码", "status": 2}
    assert data == {"ok": True}


def test_submit_agree_posts_empty_reason(monkeypatch):
    fake = _FakeClient(_FakeResp(body={"code": 200, "data": {}}))
    monkeypatch.setattr(mod, "get_case_system_client", lambda: fake)
    data = _run(submit_decision_to_internal(84177, "同意", None, None))
    assert fake.called_payload == {"reason": "", "status": 1}
    assert data == {}


def test_submit_code_zero_treated_as_success(monkeypatch):
    fake = _FakeClient(_FakeResp(body={"code": 0, "data": {"ok": 1}}))
    monkeypatch.setattr(mod, "get_case_system_client", lambda: fake)
    data = _run(submit_decision_to_internal(84177, "同意", None, None))
    assert data == {"ok": 1}


def test_submit_business_code_error_raises(monkeypatch):
    fake = _FakeClient(_FakeResp(body={"code": 500, "message": "审核失败"}))
    monkeypatch.setattr(mod, "get_case_system_client", lambda: fake)
    with pytest.raises(CaseSystemError):
        _run(submit_decision_to_internal(84177, "不同意", "其他", "缺材料"))


def test_submit_http_error_raises(monkeypatch):
    fake = _FakeClient(_FakeResp(status_code=500, body={"code": 200}))
    monkeypatch.setattr(mod, "get_case_system_client", lambda: fake)
    with pytest.raises(CaseSystemError):
        _run(submit_decision_to_internal(84177, "同意", None, None))


def test_submit_non_json_raises(monkeypatch):
    fake = _FakeClient(_FakeResp(body=None, text="<html>oops</html>"))
    monkeypatch.setattr(mod, "get_case_system_client", lambda: fake)
    with pytest.raises(CaseSystemError):
        _run(submit_decision_to_internal(84177, "同意", None, None))


def test_submit_reason_over_limit_raises_value_error():
    # reason(理由+明细)超内网 255 字上限:本地 ValueError 拦截(端点转 422),不发请求。
    long_detail = "长" * 300
    with pytest.raises(ValueError, match="255"):
        _run(submit_decision_to_internal(84177, "不同意", "其他", long_detail))


def test_submit_reason_at_limit_ok(monkeypatch):
    # 恰好 255 字(其他: 3 字 + 明细 252 字)放行。
    fake = _FakeClient(_FakeResp(body={"code": 200, "data": {}}))
    monkeypatch.setattr(mod, "get_case_system_client", lambda: fake)
    data = _run(submit_decision_to_internal(84177, "不同意", "其他", "长" * 252))
    assert data == {}
    assert len(fake.called_payload["reason"]) == 255
