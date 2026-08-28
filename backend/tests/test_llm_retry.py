"""app.ai.llm.chat_completion 的退避重试单测(假 httpx,不打真实模型服务)。"""

import asyncio

import httpx
import pytest

from app.ai import llm
from app.ai.llm import LLMCallError, chat_completion


class _FakeResp:
    def __init__(self, status_code: int, body=None):
        self.status_code = status_code
        self._body = body
        self.text = "" if body is None else str(body)

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=self)


class _FakeAsyncClient:
    """按脚本依次返回响应的假 httpx.AsyncClient(支持 async with)。"""

    script: list[_FakeResp] = []
    calls: int = 0

    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, **kwargs):
        type(self).calls += 1
        return type(self).script.pop(0)


class _FakeConfig:
    base_url = "http://fake-llm"
    api_key = "k"
    model_name = "m"
    temperature = 0.2
    max_tokens = None


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _patch_client(monkeypatch):
    _FakeAsyncClient.calls = 0
    monkeypatch.setattr(llm.httpx, "AsyncClient", _FakeAsyncClient)
    # 不重真的等 5s/15s
    monkeypatch.setattr(llm, "_RETRY_DELAYS", (0.0, 0.0))
    yield


_OK_BODY = {"choices": [{"message": {"content": "{\"conclusion\":\"通过\"}"}}]}


def test_retryable_429_then_success():
    _FakeAsyncClient.script = [
        _FakeResp(429),
        _FakeResp(200, _OK_BODY),
    ]
    out = _run(chat_completion([{"role": "user", "content": "x"}], _FakeConfig()))
    assert out == "{\"conclusion\":\"通过\"}"
    assert _FakeAsyncClient.calls == 2


def test_retry_exhausted_raises_with_detail():
    # 连续 429(3 次=首发+2 次重试)耗尽后抛 LLMCallError。
    _FakeAsyncClient.script = [_FakeResp(429), _FakeResp(429), _FakeResp(429)]
    with pytest.raises(LLMCallError, match="429"):
        _run(chat_completion([{"role": "user", "content": "x"}], _FakeConfig()))
    assert _FakeAsyncClient.calls == 3


def test_non_retryable_400_no_retry():
    # 4xx 非限流(如 400 参数错误)不重试,直接失败。
    _FakeAsyncClient.script = [_FakeResp(400)]
    with pytest.raises(LLMCallError, match="400"):
        _run(chat_completion([{"role": "user", "content": "x"}], _FakeConfig()))
    assert _FakeAsyncClient.calls == 1


def test_success_first_try():
    _FakeAsyncClient.script = [_FakeResp(200, _OK_BODY)]
    out = _run(chat_completion([{"role": "user", "content": "x"}], _FakeConfig()))
    assert "通过" in out
    assert _FakeAsyncClient.calls == 1
