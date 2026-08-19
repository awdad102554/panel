"""天眼查查企业:后端作为 MCP 客户端调用天眼查工具,解析返回的 Markdown 候选表。

天眼查 MCP 的 search_companies 工具入参 {query, page, page_size},返回 Markdown 候选
表(企业名称/统一社会信用代码/登记状态/法定代表人/注册资本/成立日期/企业ID…)。
这里解析该表格为结构化 dict 列表,前端渲染成表格;原始 Markdown 原样放 raw 供查阅。
"""

from __future__ import annotations

import json
import logging

from app.integrations.tianyancha.client import (
    TianyanchaError,
    get_tianyancha_client,
)

logger = logging.getLogger(__name__)

# 已知的"查企业候选"工具名;找不到时再按关键词兜底。
_PREFERRED_SEARCH_TOOL = "search_companies"

# 工具挑选兜底关键词:企业类权重 2,搜索/查询类权重 1。
_COMPANY_KEYWORDS = ("企业", "公司", "工商", "company", "enterprise")
_SEARCH_KEYWORDS = ("搜索", "查询", "基本信息", "search", "query", "basic", "info", "lookup")

# 入参名候选:优先找名字像"查询词"的字段。
_QUERY_PARAM_HINTS = ("query", "name", "keyword", "company", "credit", "code", "key", "search")


def _pick_company_search_tool(tools: list[dict]) -> dict | None:
    """挑"查企业候选"工具:优先精确命中 search_companies,否则关键词兜底。"""
    if not tools:
        return None
    for tool in tools:
        if tool.get("name") == _PREFERRED_SEARCH_TOOL:
            return tool
    best: dict | None = None
    best_score = -1
    for tool in tools:
        hay = f"{tool.get('name', '')} {tool.get('description', '')}".lower()
        score = sum(2 for kw in _COMPANY_KEYWORDS if kw in hay) + sum(
            1 for kw in _SEARCH_KEYWORDS if kw in hay
        )
        if score > best_score:
            best, best_score = tool, score
    return best or tools[0]


def _build_arguments(tool: dict, query: str) -> dict:
    """根据工具 inputSchema 挑入参名填入 query;无 schema 时兜底 query。"""
    schema = (tool or {}).get("inputSchema") or {}
    properties = schema.get("properties") if isinstance(schema, dict) else None
    required = schema.get("required") if isinstance(schema, dict) else []

    if isinstance(properties, dict) and properties:
        for name in properties:
            low = name.lower()
            if any(hint in low for hint in _QUERY_PARAM_HINTS):
                return {name: query}
        if isinstance(required, list) and required:
            return {str(required[0]): query}
        return {next(iter(properties)): query}
    if isinstance(required, list) and required:
        return {str(required[0]): query}
    return {"query": query}


def _extract_result_text(result: dict) -> str:
    """从 MCP tools/call 的 result 里抽出正文文本(content[].text 拼接)。"""
    if not isinstance(result, dict):
        return "" if result is None else str(result)
    content = result.get("content")
    if isinstance(content, list):
        parts = [
            item["text"]
            for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ]
        if parts:
            return "\n".join(parts)
    structured = result.get("structuredContent")
    if structured is not None:
        return structured if isinstance(structured, str) else json.dumps(structured, ensure_ascii=False)
    return ""


def _parse_table_block(lines: list[str]) -> tuple[list[str], list[dict]]:
    """把一段连续 `|...|` 表格行解析为 (表头, 行列表)。

    跳过分隔行(|---|)与重复/空表头;值按行拆分、trim;序号列 `#` 丢弃;
    「成立日期」去时间部分。空/无表头返回 ([], [])。
    """

    def _cells(line: str) -> list[str]:
        parts = line.split("|")
        if parts and parts[0].strip() == "":
            parts = parts[1:]
        if parts and parts[-1].strip() == "":
            parts = parts[:-1]
        return [p.strip() for p in parts]

    if not lines:
        return [], []
    headers = [h for h in _cells(lines[0]) if h]
    if not headers:
        return [], []

    rows: list[dict] = []
    for line in lines[1:]:
        cells = _cells(line)
        # 分隔行(全由 - : 组成)跳过
        if cells and all(c.replace("-", "").replace(":", "").strip() == "" for c in cells):
            continue
        row: dict = {}
        seen: set[str] = set()
        for i, h in enumerate(headers):
            if h == "#" or h in seen:
                continue  # 丢弃序号列;重复列名(如第二个"成立日期")跳过
            seen.add(h)
            cell = cells[i] if i < len(cells) else ""
            if h == "成立日期":
                cell = cell.split(" ")[0]  # 去掉 "2004-11-10 00:00:00.0" 的时间部分
            row[h] = cell
        if row:
            rows.append(row)
    return headers, rows


def _parse_markdown_table(text: str) -> list[dict]:
    """解析 Markdown 里第一个表格(候选企业表)为 dict 列表。无表格返回 []。"""
    if not text:
        return []
    lines = [ln for ln in text.splitlines() if ln.strip().startswith("|")]
    if not lines:
        return []
    _, rows = _parse_table_block(lines)
    return rows


# 企业详情概览字段的固定展示顺序(原始字段名 → 展示名);未列出的字段(分页/冗余/内部字段)丢弃。
_OVERVIEW_FIELD_ORDER: list[tuple[str, str]] = [
    ("企业名称", "企业名称"),
    ("统一社会信用代码", "统一社会信用代码"),
    ("法定代表人", "法定代表人"),
    ("登记状态", "登记状态"),
    ("注册资本", "注册资本"),
    ("实缴资本", "实缴资本"),
    ("实缴资本币种", "实缴资本币种"),
    ("成立日期", "成立日期"),
    ("核准日期", "核准日期"),
    ("营业期限起", "营业期限起"),
    ("企业类型", "企业类型"),
    ("行业", "行业"),
    ("经营范围", "经营范围"),
    ("注册地址", "注册地址"),
    ("城市", "城市"),
    ("区县", "区县"),
    ("省份", "省份"),
    ("联系电话", "联系电话"),
    ("邮箱", "邮箱"),
    ("官网", "官网"),
    ("登记机关", "登记机关"),
    ("人员规模", "人员规模"),
    ("参保人数", "参保人数"),
    ("曾用名", "曾用名"),
    ("标签", "标签"),
    ("profile", "企业简介"),
    ("经度", "经度"),
    ("纬度", "纬度"),
]


def _parse_profile_markdown(text: str) -> dict:
    """解析 get_company_basic_profile 的 Markdown 为 {overview, details}。

    - overview: 所有 `字段/值` 两列表格合并(按字段名去重,先见优先)。
    - details: 其余多列表格(联系电话明细、曾用名明细等),每项 {title, headers, rows}。
    """
    overview: list[dict] = []
    seen_keys: set[str] = set()
    details: list[dict] = []

    lines = text.splitlines() if text else []
    heading = ""
    h2 = ""
    i = 0
    n = len(lines)
    while i < n:
        stripped = lines[i].strip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            heading = stripped.lstrip("#").strip()
            if level == 2:
                h2 = heading
            i += 1
            continue
        if stripped.startswith("|"):
            block: list[str] = []
            while i < n and lines[i].strip().startswith("|"):
                block.append(lines[i])
                i += 1
            headers, rows = _parse_table_block(block)
            if not rows:
                continue
            if len(headers) == 2 and headers[0] == "字段" and headers[1] == "值":
                for row in rows:
                    key = row.get("字段", "")
                    value = row.get("值", "")
                    if not key or key in seen_keys:
                        continue
                    seen_keys.add(key)
                    overview.append({"字段": key, "值": value})
            else:
                # 标题取最近一级标题;若太笼统(如"明细")则带上二级章节名(如"所在园区")。
                base = heading.split("（")[0].strip()
                generic = base in ("明细", "概览字段") or heading == ""
                title = f"{h2} · {heading}" if generic and h2 else (heading or h2)
                details.append(
                    {
                        "title": title,
                        "headers": [h for h in headers if h != "#"],
                        "rows": rows,
                    }
                )
            continue
        i += 1

    # 固定展示顺序 + 丢弃噪音字段与空值(注册资本为 "-" 等)
    value_by_key = {row["字段"]: row["值"] for row in overview}
    overview = [
        {"字段": label, "值": value_by_key[raw]}
        for raw, label in _OVERVIEW_FIELD_ORDER
        if raw in value_by_key and value_by_key[raw] not in ("", "-", "—", "--")
    ]
    return {"overview": overview, "details": details}


async def search_company(query: str, client=None) -> dict:
    """查企业基本信息,返回 {query, tool, fields, raw};fields 为候选企业 dict 列表。"""
    client = client or get_tianyancha_client()
    if client is None:
        raise TianyanchaError("tianyancha_not_configured")

    tools = await client.list_tools()
    tool = _pick_company_search_tool(tools)
    if tool is None:
        raise TianyanchaError("no_tools_available")

    arguments = _build_arguments(tool, query)
    result = await client.call_tool(tool["name"], arguments)
    text = _extract_result_text(result)
    fields = _parse_markdown_table(text)
    return {
        "query": query,
        "tool": tool.get("name"),
        "fields": fields,
        "raw": text,
    }


async def get_company_details(company_name: str, client=None) -> dict:
    """查企业基础详情:调用 get_company_basic_profile,解析为概览字段 + 明细表。"""
    client = client or get_tianyancha_client()
    if client is None:
        raise TianyanchaError("tianyancha_not_configured")

    result = await client.call_tool(
        "get_company_basic_profile", {"company_name": company_name}
    )
    text = _extract_result_text(result)
    parsed = _parse_profile_markdown(text)
    return {
        "company_name": company_name,
        "tool": "get_company_basic_profile",
        "overview": parsed["overview"],
        "details": parsed["details"],
        "raw": text,
    }
