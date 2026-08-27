"""案件记事本 + IP→用户名绑定单测:subject_key 构造、客户端 IP 提取、subject 解析、用户名绑定,不打真 DB。"""

import asyncio

import pytest

from app.api.v1.case_tags import _extract_client_ip
from app.models.user_ip import UserIpBinding
from app.services.case_tags import (
    bind_username,
    get_username_by_ip,
    normalize_phrase,
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
        raw_payload = {}  # 无 next_step,不是案前调解
        is_paused = False
        current_step = None

    assert asyncio.run(resolve_subject_stage(_FakeDB(Row()), "ext:123")) == "receive"


def test_resolve_subject_stage_external_returns_stage_enum_value():
    class EnumLike:
        value = "handle"

    class Row:
        stage = EnumLike()
        raw_payload = {}
        is_paused = False
        current_step = None

    assert asyncio.run(resolve_subject_stage(_FakeDB(Row()), "ext:456")) == "handle"


def test_resolve_subject_stage_external_paused_by_flag():
    class Row:
        stage = "handle"
        raw_payload = {}
        is_paused = True
        current_step = None

    assert asyncio.run(resolve_subject_stage(_FakeDB(Row()), "ext:999")) == "paused"


def test_resolve_subject_stage_external_paused_by_current_step():
    class Row:
        stage = "handle"
        raw_payload = {}
        is_paused = False
        current_step = "审理中止"

    assert asyncio.run(resolve_subject_stage(_FakeDB(Row()), "ext:1000")) == "paused"


@pytest.mark.parametrize(
    ("current_step", "expected"),
    [
        ("审理中止", "paused"),
        ("组织调解", "mediation"),
        ("仲裁裁决中", "deciding"),
        ("待开庭安排", "pending_hearing"),
        ("待开庭审理", "pending_trial"),
        ("审理事项进行中", "in_progress"),
        ("已结案", "closed"),
        ("已归档", "archived"),
    ],
)
def test_resolve_subject_stage_handle_substep(current_step, expected):
    cs = current_step  # 类体作用域里 current_step = current_step 会遮蔽参数,先落本地变量

    class Row:
        stage = "handle"
        raw_payload = {}
        is_paused = False
        current_step = cs

    assert asyncio.run(resolve_subject_stage(_FakeDB(Row()), "ext:900")) == expected


def test_resolve_subject_stage_handle_unknown_substep_falls_back_to_handle():
    class Row:
        stage = "handle"
        raw_payload = {}
        is_paused = False
        current_step = "未知子状态"

    assert asyncio.run(resolve_subject_stage(_FakeDB(Row()), "ext:901")) == "handle"


def test_resolve_subject_stage_external_pre_mediation_next_step_int():
    class Row:
        stage = "receive"
        raw_payload = {"next_step": 3}

    assert asyncio.run(resolve_subject_stage(_FakeDB(Row()), "ext:789")) == "pre_mediation"


def test_resolve_subject_stage_external_pre_mediation_next_step_str():
    class Row:
        stage = "receive"
        raw_payload = {"next_step": "3"}

    assert asyncio.run(resolve_subject_stage(_FakeDB(Row()), "ext:790")) == "pre_mediation"


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


# ---- 快捷内容校验 ----


def test_normalize_phrase_strips_whitespace():
    assert normalize_phrase("  已电话联系申请人  ") == "已电话联系申请人"


def test_normalize_phrase_empty_rejected():
    with pytest.raises(ValueError):
        normalize_phrase("   ")


def test_normalize_phrase_too_long_rejected():
    with pytest.raises(ValueError):
        normalize_phrase("长" * 101)


def test_normalize_phrase_max_len_ok():
    assert len(normalize_phrase("长" * 100)) == 100


# ---- 记事本总览(近 N 天有记事的案件) ----

from datetime import datetime, timedelta  # noqa: E402

from app.models.case_tag import CaseTag  # noqa: E402
from app.services.case_tags import tags_overview  # noqa: E402


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeListResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _FakeScalars(self._rows)


class _QueueDB:
    """按调用顺序返回预设结果的假库(适配 tags_overview 的多轮查询)。"""

    def __init__(self, *results):
        self._queue = [_FakeListResult(r) for r in results]

    async def execute(self, stmt):
        assert self._queue, "意外的额外查询"
        return self._queue.pop(0)


def _tag(subject_key, content, days_ago, operator="张三"):
    t = CaseTag(subject_key=subject_key, content=content, stage="receive", operator=operator, client_ip="1.1.1.1")
    t.created_at = datetime.utcnow() - timedelta(days=days_ago)
    return t


def test_tags_overview_groups_and_resolves_current_case():
    class Row:
        external_case_id = "100"
        case_no = "永劳人仲案字[2026]100号"
        stage = "handle"
        current_step = "仲裁裁决中"
        raw_payload = {"applicant": "张三", "respondent": "某公司"}

    mysql_db = _QueueDB(
        [_tag("ext:100", "已电话联系", 3), _tag("ext:100", "对方同意调解", 1), _tag("ext:gone", "旧案件记事", 2)],
    )
    # PG 查询序列:1) 快照批量 2) 缺失案件查绑定(空)
    pg_db = _QueueDB([Row()], [])

    items = asyncio.run(tags_overview(pg_db, mysql_db, 30))
    assert len(items) == 2
    # 最近记事倒序:ext:gone(2 天前)应在 ext:100(1 天前)之后?不——1 天前更新,排前
    first = items[0]
    assert first["subject_key"] == "ext:100"
    assert first["case_no"] == "永劳人仲案字[2026]100号"
    assert first["applicant"] == "张三"
    assert first["respondent"] == "某公司"
    assert first["stage"] == "deciding"  # current_step=仲裁裁决中
    assert first["tag_count"] == 2
    assert first["last_content"] == "对方同意调解"
    assert first["exists"] is True

    gone = items[1]
    assert gone["subject_key"] == "ext:gone"
    assert gone["exists"] is False
    assert gone["case_no"] is None


def test_tags_overview_bound_receive_shows_handle_case_no():
    """案前调解收件(ext:200)已立案但记事未转移:经绑定表解析到立案案号。"""

    class Binding:
        receive_external_case_id = "200"
        handle_external_case_id = "300"

    class HandleRow:
        external_case_id = "300"
        case_no = "永劳人仲案字[2026]300号"
        stage = "handle"
        current_step = None
        is_paused = False
        raw_payload = {"applicant": "李四", "respondent": "某厂"}

    mysql_db = _QueueDB([_tag("ext:200", "调解中", 1)])
    # PG 查询序列:1) 快照(无 200) 2) 绑定(200→300) 3) handle 行
    pg_db = _QueueDB([], [Binding()], [HandleRow()])

    items = asyncio.run(tags_overview(pg_db, mysql_db, 30))
    assert len(items) == 1
    assert items[0]["case_no"] == "永劳人仲案字[2026]300号"
    assert items[0]["applicant"] == "李四"
    assert items[0]["exists"] is True


def test_tags_overview_window_filters_old_tags():
    # 10 天前的记事儿在 days=7 窗口内:MySQL 查询由 SQL 过滤,这里只验证
    # 空结果(窗口内无记事)不报错。
    mysql_db = _QueueDB([])
    pg_db = _QueueDB()
    assert asyncio.run(tags_overview(pg_db, mysql_db, 7)) == []
