"""案件记事本 + IP→用户名绑定单测:subject_key 构造、客户端 IP 提取、subject 解析、用户名绑定,不打真 DB。"""

import asyncio

import pytest

from app.api.v1.case_tags import _extract_client_ip
from app.models.user_ip import UserIpBinding
from app.services.case_tags import (
    bind_username,
    get_username_by_ip,
    resolve_subject_stage,
    subject_key_for_external,
    subject_key_for_virtual,
)


# ---- subject_key 构造 ----


def test_subject_key_helpers():
    assert subject_key_for_external("308623") == "ext:308623"
    assert subject_key_for_virtual("a1b2c3d4") == "virt:a1b2c3d4"


# ---- 客户端 IP 提取 ----


def test_extract_client_ip_prefers_real_ip_over_spoofed_forwarded():
    # 客户端可伪造 XFF 首跳;X-Real-IP 是 nginx 覆盖的 $remote_addr,优先且不可伪造。
    assert _extract_client_ip("1.2.3.4, 10.0.0.5", "10.0.0.5", "127.0.0.1") == "10.0.0.5"


def test_extract_client_ip_forwarded_last_hop_when_no_real():
    # 无 X-Real-IP 时取 XFF 末跳(nginx 追加的 $remote_addr),而非可伪造的首跳。
    assert _extract_client_ip("1.2.3.4, 10.0.0.5", None, "127.0.0.1") == "10.0.0.5"


def test_extract_client_ip_falls_back_to_host():
    assert _extract_client_ip(None, None, "127.0.0.1") == "127.0.0.1"
    assert _extract_client_ip("", "", None) == ""


# ---- subject 解析(存在性校验 + 环节) ----


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeDB:
    """只实现 resolve_subject_stage / get_username_by_ip 用到的 execute()。"""

    def __init__(self, result):
        self._result = result

    async def execute(self, stmt):
        return _FakeResult(self._result)


def test_resolve_subject_stage_invalid_key():
    with pytest.raises(ValueError):
        asyncio.run(resolve_subject_stage(_FakeDB(None), "bad-key"))
    with pytest.raises(ValueError):
        asyncio.run(resolve_subject_stage(_FakeDB(None), "ext:"))


def test_resolve_subject_stage_external_not_found():
    with pytest.raises(LookupError):
        asyncio.run(resolve_subject_stage(_FakeDB(None), "ext:missing"))


def test_resolve_subject_stage_external_returns_stage_string():
    class Row:
        stage = "receive"  # stage 列是 String,读回为 str

    assert asyncio.run(resolve_subject_stage(_FakeDB(Row()), "ext:123")) == "receive"


def test_resolve_subject_stage_external_returns_stage_enum_value():
    class EnumLike:
        value = "handle"

    class Row:
        stage = EnumLike()

    assert asyncio.run(resolve_subject_stage(_FakeDB(Row()), "ext:456")) == "handle"


# ---- IP→用户名绑定 ----


class _Row:
    def __init__(self, username):
        self.username = username


def test_get_username_by_ip_returns_username():
    assert asyncio.run(get_username_by_ip(_FakeDB(_Row("张三")), "10.0.0.5")) == "张三"


def test_get_username_by_ip_unbound_returns_none():
    assert asyncio.run(get_username_by_ip(_FakeDB(None), "10.0.0.9")) is None


def test_get_username_by_ip_empty_ip_returns_none():
    assert asyncio.run(get_username_by_ip(_FakeDB(_Row("张三")), "")) is None


class _FakeMysqlDB:
    """支持 bind_username 的极简假库(add/commit/refresh)。"""

    def __init__(self, existing):
        self._result = _FakeResult(existing)
        self.added = []
        self.committed = 0
        self.refreshed = []

    async def execute(self, stmt):
        return self._result

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed += 1

    async def refresh(self, obj):
        self.refreshed.append(obj)


def test_bind_username_creates_new():
    db = _FakeMysqlDB(None)
    row = asyncio.run(bind_username(db, "10.0.0.5", "李四"))
    assert row.username == "李四"
    assert len(db.added) == 1
    assert db.committed == 1


def test_bind_username_updates_existing():
    existing = UserIpBinding(ip="10.0.0.5", username="旧名")
    db = _FakeMysqlDB(existing)
    row = asyncio.run(bind_username(db, "10.0.0.5", "新名"))
    assert row.username == "新名"
    assert db.added == []
    assert db.committed == 1
