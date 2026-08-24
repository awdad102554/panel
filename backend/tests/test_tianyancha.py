"""天眼查 MCP 集成单测:纯函数(SSE 解析 / 工具挑选 / 入参构造 / Markdown 表格解析),不打外网。"""

import asyncio

import pytest

from app.integrations.tianyancha.client import (
    TianyanchaAuthError,
    TianyanchaError,
    _looks_auth_error,
    _parse_sse_messages,
)
from app.services.tianyancha_lookup import (
    _build_arguments,
    _extract_main_personnel,
    _parse_markdown_table,
    _parse_profile_markdown,
    _pick_company_search_tool,
    get_company_details,
    search_company,
)
from app.services.tianyancha_settings import clean_api_key, mask_api_key


# ---- SSE 响应解析 ----


def test_parse_sse_messages_extracts_multiple_events():
    sse = (
        'event: message\n'
        'data: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n'
        'event: message\n'
        'data: {"jsonrpc":"2.0","id":2,"result":{"tools":[]}}\n\n'
    )
    msgs = _parse_sse_messages(sse)
    assert len(msgs) == 2
    assert msgs[0]["id"] == 1
    assert msgs[1]["id"] == 2


def test_parse_sse_messages_multiline_data_and_comment():
    sse = (
        ': keepalive\n\n'
        'event: message\n'
        'data: {"jsonrpc":"2.0",\n'
        'data: "id":1,"result":{}}\n\n'
    )
    msgs = _parse_sse_messages(sse)
    assert len(msgs) == 1
    assert msgs[0]["id"] == 1


def test_parse_sse_messages_skips_bad_json():
    assert _parse_sse_messages("data: not-json\n\n") == []


# ---- Markdown 表格解析 ----


_SAMPLE_MD = (
    "> 后续调用建议…\n\n"
    "# 企业候选列表\n\n"
    "| # | 企业名称 | 统一社会信用代码 | 登记状态 | 法定代表人 | 注册资本 | 成立日期 | 企业类型 | 成立日期 | 企业ID | 匹配类型 |\n"
    "|---|---|---|---|---|---|---|---|---|---|---|\n"
    "| 1 | 乐视网信息技术（北京）股份有限公司 | 911100007693890511 | 存续 | 刘延峰 | 398944.0192万人民币 | 2004-11-10 00:00:00.0 | 1 | 2004-11-10 00:00:00.0 | 14427175 | 公司名称匹配 |\n"
    "| 2 | 乐融致新电子科技（天津）有限公司 | 91120116589764942R | 存续 | 毛丙龙 | 37459.6083万人民币 | 2012-02-07 00:00:00.0 | 1 | 2012-02-07 00:00:00.0 | 3176559214 | 股东信息匹配 |\n"
)


def test_parse_markdown_table_extracts_rows():
    rows = _parse_markdown_table(_SAMPLE_MD)
    assert len(rows) == 2
    first = rows[0]
    assert first["企业名称"] == "乐视网信息技术（北京）股份有限公司"
    assert first["统一社会信用代码"] == "911100007693890511"
    assert first["登记状态"] == "存续"
    assert first["法定代表人"] == "刘延峰"
    assert first["注册资本"] == "398944.0192万人民币"
    assert first["成立日期"] == "2004-11-10"  # 时间部分被去掉
    assert first["企业ID"] == "14427175"
    assert first["匹配类型"] == "公司名称匹配"
    # "#" 列被丢弃;重复的"成立日期"只保留一个
    assert "#" not in first
    assert list(first).count("成立日期") == 1


def test_parse_markdown_table_empty():
    assert _parse_markdown_table("") == []
    assert _parse_markdown_table("没有表格") == []


# ---- 工具挑选 ----


def test_pick_company_search_tool_prefers_search_companies():
    tools = [
        {"name": "get_company_basic_profile", "description": "公司基础画像"},
        {"name": "search_companies", "description": "搜索公司候选列表"},
    ]
    assert _pick_company_search_tool(tools)["name"] == "search_companies"


def test_pick_company_search_tool_fallback_first():
    tools = [{"name": "toolA"}, {"name": "toolB"}]
    assert _pick_company_search_tool(tools)["name"] == "toolA"


def test_pick_company_search_tool_empty():
    assert _pick_company_search_tool([]) is None


# ---- 入参构造 ----


def test_build_arguments_picks_query_hint():
    tool = {
        "inputSchema": {
            "properties": {"pageSize": {"type": "integer"}, "companyName": {"type": "string"}}
        }
    }
    assert _build_arguments(tool, "乐视") == {"companyName": "乐视"}


def test_build_arguments_uses_required_when_no_hint():
    tool = {"inputSchema": {"properties": {"a": {}, "b": {}}, "required": ["b"]}}
    assert _build_arguments(tool, "x") == {"b": "x"}


def test_build_arguments_no_schema_fallback_query():
    assert _build_arguments({}, "乐视") == {"query": "乐视"}


# ---- API Key 配置存取 ----


def test_clean_api_key_strips_and_accepts_empty():
    assert clean_api_key("  abc123  ") == "abc123"
    assert clean_api_key("") == ""
    assert clean_api_key(None) == ""


def test_clean_api_key_rejects_too_long():
    with pytest.raises(ValueError):
        clean_api_key("x" * 129)


def test_mask_api_key():
    assert mask_api_key("abcd1234efgh") == "••••efgh"
    assert mask_api_key("abc") == "••••"
    assert mask_api_key("") == ""


# ---- 服务编排(假客户端,不打外网) ----


_PROFILE_MD = (
    "# 公司基础画像：测试公司\n\n"
    "## 基础工商登记\n\n"
    "### 企业基本信息\n\n"
    "#### 概览字段\n\n"
    "| 字段 | 值 |\n|---|---|\n"
    "| 企业名称 | 测试公司 |\n"
    "| 联系电话 | 13800000000 |\n"
    "\n## 联系方式\n\n"
    "### 概览字段\n\n"
    "| 字段 | 值 |\n|---|---|\n"
    "| 邮箱 | a@b.com |\n"
    "| 联系电话 | 13911112222 |\n"
    "\n### 联系电话明细（2 条）\n\n"
    "| # | 来源 | 号码类型 | 联系电话 | 标签 |\n"
    "|---|---|---|---|---|\n"
    "| 1 | 年报 | 正常电话 | 13800000000 | 可联系 |\n"
    "| 2 | 公开途径 | 大陆座机 | 010-12345678 | 固定电话 |\n"
)


def test_parse_profile_markdown_splits_overview_and_details():
    parsed = _parse_profile_markdown(_PROFILE_MD)
    overview = parsed["overview"]
    # 概览字段按字段名去重:联系电话 取首见值(基础工商里的),邮箱并入
    assert [f["字段"] for f in overview] == ["企业名称", "联系电话", "邮箱"]
    assert overview[1]["值"] == "13800000000"
    # 明细表只保留一张(联系电话明细),# 列被剔除
    assert len(parsed["details"]) == 1
    det = parsed["details"][0]
    assert det["title"] == "联系电话明细（2 条）"
    assert det["headers"] == ["来源", "号码类型", "联系电话", "标签"]
    assert det["rows"][0]["联系电话"] == "13800000000"


def test_parse_profile_markdown_empty():
    assert _parse_profile_markdown("") == {"overview": [], "details": []}


def test_parse_profile_markdown_filters_noise_and_orders():
    md = (
        "## 基础工商登记\n\n"
        "### 概览字段\n\n"
        "| 字段 | 值 |\n|---|---|\n"
        "| 企业名称 | 某公司 |\n"
        "| 注册资本 | - |\n"
        "| 联系电话 | 13800000000 |\n"
        "| profile | 简介文本 |\n"
        "| 总数 | 3 |\n"
        "| pageNum | 1 |\n"
        "| 邮箱 | a@b.com |\n"
    )
    parsed = _parse_profile_markdown(md)
    fields = [f["字段"] for f in parsed["overview"]]
    # 固定顺序 + profile 改名企业简介;注册资本 "-" 与 分页字段 总数/pageNum 丢弃
    assert fields == ["企业名称", "联系电话", "邮箱", "企业简介"]
    assert parsed["overview"][3]["值"] == "简介文本"


def test_parse_profile_markdown_prefixes_generic_detail_title():
    md = (
        "## 所在园区\n\n"
        "### 明细（1 条）\n\n"
        "| # | 园区名称 | 园区面积 |\n|---|---|---|\n"
        "| 1 | 腾讯大厦 | 139 |\n"
    )
    parsed = _parse_profile_markdown(md)
    assert parsed["details"][0]["title"] == "所在园区 · 明细（1 条）"


def test_parse_profile_markdown_keeps_specific_detail_title():
    md = (
        "## 联系方式\n\n"
        "### 联系电话明细（2 条）\n\n"
        "| # | 来源 | 联系电话 |\n|---|---|---|\n"
        "| 1 | 年报 | 13800000000 |\n"
    )
    parsed = _parse_profile_markdown(md)
    assert parsed["details"][0]["title"] == "联系电话明细（2 条）"


# ---- 鉴权错误识别 ----


def test_looks_auth_error_matches_hints():
    assert _looks_auth_error("Unauthorized: invalid api key") is True
    assert _looks_auth_error("鉴权失败") is True
    assert _looks_auth_error("rpc internal error") is False


def test_tianyancha_auth_error_is_subclass():
    assert issubclass(TianyanchaAuthError, TianyanchaError)


_PEOPLE_MD = (
    "# 公司人员列表：测试公司\n\n"
    "## 主要人员\n\n"
    "### 主要人员（2 条）\n\n"
    "| # | 姓名 | 职务 |\n|---|---|---|\n"
    "| 1 | 张三 | 执行董事兼总经理 |\n"
    "| 2 | 李四 | 监事 |\n"
    "\n## 核心团队\n\n"
    "### 明细（1 条）\n\n"
    "| # | 名称 | 标题 |\n|---|---|---|\n"
    "| 1 | 张三 | 创始人 |\n"
)


def test_extract_main_personnel_returns_first_table_only():
    rows = _extract_main_personnel(_PEOPLE_MD)
    assert len(rows) == 2
    assert rows[0] == {"姓名": "张三", "职务": "执行董事兼总经理"}
    assert rows[1] == {"姓名": "李四", "职务": "监事"}


def test_extract_main_personnel_empty_or_wrong_columns():
    assert _extract_main_personnel("") == []
    # 首表不含「姓名/职务」列(如只有 名称/标题),视为无主要人员
    md = "| # | 名称 | 标题 |\n|---|---|---|\n| 1 | 张三 | 创始人 |\n"
    assert _extract_main_personnel(md) == []


def test_get_company_details_end_to_end_with_fake_client():
    class FakeClient:
        async def call_tool(self, name, arguments):
            assert arguments == {"company_name": "测试公司"}
            if name == "get_company_basic_profile":
                return {"content": [{"type": "text", "text": _PROFILE_MD}]}
            if name == "get_company_people":
                return {"content": [{"type": "text", "text": _PEOPLE_MD}]}
            raise AssertionError(f"unexpected tool: {name}")

    data = asyncio.run(get_company_details("测试公司", client=FakeClient()))
    assert data["tool"] == "get_company_basic_profile"
    assert data["company_name"] == "测试公司"
    assert data["overview"][0]["字段"] == "企业名称"
    # 主要人员表成为首个明细,姓名/职务列正确;联系电话明细顺延到第二位
    assert data["details"][0]["title"] == "主要人员（2 条）"
    assert data["details"][0]["headers"] == ["姓名", "职务"]
    assert data["details"][0]["rows"][0]["姓名"] == "张三"
    assert data["details"][1]["title"] == "联系电话明细（2 条）"


def test_get_company_details_adds_legal_rep_position():
    profile_md = (
        "### 企业基本信息\n\n"
        "#### 概览字段\n\n"
        "| 字段 | 值 |\n|---|---|\n"
        "| 企业名称 | 测试公司 |\n"
        "| 法定代表人 | 张三 |\n"
    )

    class FakeClient:
        async def call_tool(self, name, arguments):
            if name == "get_company_basic_profile":
                return {"content": [{"type": "text", "text": profile_md}]}
            if name == "get_company_people":
                return {"content": [{"type": "text", "text": _PEOPLE_MD}]}
            raise AssertionError(f"unexpected tool: {name}")

    data = asyncio.run(get_company_details("测试公司", client=FakeClient()))
    fields = [f["字段"] for f in data["overview"]]
    # 职位合并进「法定代表人」字段,不再单独出现「法定代表人职务」
    assert "法定代表人职务" not in fields
    assert data["overview"][fields.index("法定代表人")]["值"] == "张三（执行董事兼总经理）"


def test_get_company_details_people_failure_degrades():
    class FakeClient:
        async def call_tool(self, name, arguments):
            if name == "get_company_basic_profile":
                return {"content": [{"type": "text", "text": _PROFILE_MD}]}
            raise TianyanchaError("quota exceeded")

    data = asyncio.run(get_company_details("测试公司", client=FakeClient()))
    # 拉取主要人员失败不阻断:仅基础画像,无「主要人员」明细
    assert data["details"][0]["title"] == "联系电话明细（2 条）"


def test_search_company_end_to_end_with_fake_client():
    class FakeClient:
        async def list_tools(self):
            return [
                {
                    "name": "search_companies",
                    "description": "搜索公司候选列表",
                    "inputSchema": {
                        "properties": {"query": {"type": "string"}, "page": {"type": "number"}},
                        "required": ["query"],
                    },
                }
            ]

        async def call_tool(self, name, arguments):
            assert name == "search_companies"
            assert arguments == {"query": "乐视"}
            return {"content": [{"type": "text", "text": _SAMPLE_MD}]}

    data = asyncio.run(search_company("乐视", client=FakeClient()))
    assert data["tool"] == "search_companies"
    assert data["fields"][0]["企业名称"] == "乐视网信息技术（北京）股份有限公司"
    assert data["fields"][0]["统一社会信用代码"] == "911100007693890511"
