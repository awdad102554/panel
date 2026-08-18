"""AI 预约审查核心服务。

把内网「线上预约待审核」案件的详情(仲裁请求/事实理由/证据材料/当事人/代理人)
压成结构化摘要,配合 docs/reserve-ai-review-prompt.md 里总结的审查规则提示词,
交给已配置的 AI 模型产出「通过/补正/驳回」建议。结论仅作初筛建议,不写回内网。
"""

from __future__ import annotations

import json
from typing import Any

from app.integrations.case_system.client import (
    CaseSystemClient,
    CaseSystemError,
)

# 审查规则提示词,直接采用 docs/reserve-ai-review-prompt.md 第三节(基于 32 条历史驳回记录总结)。
RESERVE_REVIEW_SYSTEM_PROMPT = """你是劳动人事争议仲裁委员会的预申请审查助手。请根据申请人提交的线上预约（预申请）
内容，按以下规则审查并给出结论。

# 审查规则
1. 被申请人必须明确:单位全称准确、与工商登记一致、有可送达地址;劳动者身份信息完整。
2. 仲裁请求必须明确具体:请求事项清晰,涉金额的必须有金额和计算依据;
   请求须属于劳动争议受案范围(工资、经济补偿、赔偿金、社会保险、确认劳动关系等)。
3. 事实和理由必须完整:劳动关系起止时间、岗位、工资标准、争议经过齐全,能支撑请求。
4. 证据材料齐备性:身份证明、劳动关系证明、工资流水、被申请人工商信息等。
5. 管辖:劳动合同履行地或用人单位所在地属本委辖区。

# 结论只能是以下三种之一
- "通过":同时满足 1-5。
- "补正":争议明确但材料/表述有缺项,可在 3 天内补正的;
  必须逐条列出需要补正的具体内容(补正指引写给申请人看,语气通俗)。
- "驳回":被申请人不明确、请求或事实理由不明确、不属于受案范围、
  或经核实已无争议(如工资已结清)等;必须引用具体规则并写明理由。

# 输出格式(只输出 JSON,不要其他内容)
{
  "conclusion": "通过" | "补正" | "驳回",
  "reason": "给申请人的结论说明(通俗、具体,可直接作为系统驳回/补正理由展示)",
  "issues": ["审查发现的问题点,逐条列出"],
  "missing_materials": ["缺少的材料(仅补正时填)"],
  "rule_refs": ["命中的审查规则编号"],
  "checks": [
    {"rule_id": "1", "rule_name": "被申请人明确性", "passed": true, "note": "该项是否通过及一句说明"},
    {"rule_id": "2", "rule_name": "仲裁请求明确性", "passed": true, "note": "..."},
    {"rule_id": "3", "rule_name": "事实和理由完整性", "passed": true, "note": "..."},
    {"rule_id": "4", "rule_name": "证据材料齐备性", "passed": true, "note": "..."},
    {"rule_id": "5", "rule_name": "管辖", "passed": true, "note": "..."}
  ]
}

# 注意
- checks 必须覆盖全部 5 条规则;passed 三态取值:
  true = 该项完全满足、零缺陷;
  false = 有缺项/不一致/明显不满足;
  null = 信息不全、无法自动确认、需人工核验。
  硬约束:只要该项存在任何缺项、字段未填写/未上传、内容不一致或需人工核验,passed 一律不得为 true——不确定就填 null,严禁"note 里列了问题却判通过"。
- 当事人字段中的 card_image_front/card_image_reverse 标记「身份证/证照照片 已上传/未上传」——「已上传」即视为该证件已提交,不要因看不到图片内容而判「缺少该证件」;不臆断图片内容。
- 不确定能否核验的信息(如工商信息真伪)不要臆断,该项 passed 填 null 并在 note 里写"需人工核验"。
- 金额计算只核对请求内部的自洽性,不判断实体对错。
- 驳回是严厉结论:证据不足支撑"明确驳回"时,降级为"补正"并在 reason 中说明。
"""

_VALID_CONCLUSIONS = ("通过", "补正", "驳回")

# 审查规则维度(与提示词 1-5 一一对应),用于把模型 checks 归一化、缺失时按 rule_refs 兜底。
_RULES: tuple[tuple[str, str], ...] = (
    ("1", "被申请人明确性"),
    ("2", "仲裁请求明确性"),
    ("3", "事实和理由完整性"),
    ("4", "证据材料齐备性"),
    ("5", "管辖"),
)


def failure_result(reason: str) -> dict[str, Any]:
    """审查失败/无法审查时的兜底结论(非「通过/补正/驳回」三种之一)。"""
    return {
        "conclusion": "审查失败",
        "reason": reason,
        "issues": [],
        "missing_materials": [],
        "rule_refs": [],
        "checks": [],
    }


async def fetch_reserve_detail(client: CaseSystemClient, row_id: int) -> dict:
    """GET /v1/api/admin/arb/{row_id}/reserve,取 data.data(预约完整提交内容)。"""
    resp = await client.get(f"/v1/api/admin/arb/{row_id}/reserve")
    if resp.status_code != 200:
        raise CaseSystemError(f"reserve_detail_http_{resp.status_code}")
    body = resp.json()
    outer = body.get("data") if isinstance(body, dict) else None
    inner = outer.get("data") if isinstance(outer, dict) else None
    if not isinstance(inner, dict):
        raise CaseSystemError("reserve_detail_bad_body")
    return inner


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ("" if value is None else str(value))


def _yesno(value: Any) -> str:
    """把 0/1 布尔字段归一为「是/否」;空值返回空串(前端显示 —),其他值原样转字符串。"""
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "是", "yes"):
            return "是"
        if v in ("0", "false", "否", "no"):
            return "否"
        return value
    if value == 1:
        return "是"
    if value == 0:
        return "否"
    return str(value)


def _uploaded(value: Any) -> str:
    """把证件照片路径/URL 归一为「已上传/未上传」,只传状态、不传图片内容。"""
    return "已上传" if _str(value) else "未上传"


def _list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if v not in (None, "")]


def _default_checks(rule_refs: list[str]) -> list[dict[str, Any]]:
    """模型未输出 checks 时,按命中的 rule_refs 兜底生成 5 项(命中=不通过)。"""
    refs = set(rule_refs)
    return [
        {
            "rule_id": rid,
            "rule_name": name,
            "passed": rid not in refs,
            "note": "该项审查通过" if rid not in refs else "该项审查未通过",
        }
        for rid, name in _RULES
    ]


# note 命中任一关键词即视为「该项有缺陷/需人工核验」,用于兜底纠正模型「note 列了问题却 passed=true」的自相矛盾。
_NOTE_PROBLEM_HINTS = (
    "需人工核验", "待核验", "需核验", "需核实", "待核实", "待确认",
    "空缺", "缺少", "缺失", "缺项", "未填写", "未上传", "未提供",
    "无法证明", "不一致", "矛盾", "不符", "不完整", "不自洽",
)


def _note_has_problem(note: str) -> bool:
    return any(h in note for h in _NOTE_PROBLEM_HINTS)


def _normalize_checks(obj: dict[str, Any], rule_refs: list[str]) -> list[dict[str, Any]]:
    """归一化模型 checks 输出;缺失/为空时兜底,并补齐漏给的规则维度。"""
    raw = obj.get("checks")
    if not isinstance(raw, list) or not raw:
        return _default_checks(rule_refs)

    out: list[dict[str, Any]] = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        passed = c.get("passed")
        if isinstance(passed, str):
            passed = passed.strip().lower() in ("true", "通过", "是", "1", "yes")
        elif not isinstance(passed, bool):
            passed = None
        out.append(
            {
                "rule_id": _str(c.get("rule_id") or c.get("id")),
                "rule_name": _str(c.get("rule_name") or c.get("name")),
                "passed": passed,
                "note": _str(c.get("note") or c.get("comment") or c.get("detail")),
            }
        )

    if not out:
        return _default_checks(rule_refs)

    refs = set(rule_refs)
    existing = {c["rule_id"] for c in out}
    for rid, name in _RULES:
        if rid not in existing:
            out.append(
                {
                    "rule_id": rid,
                    "rule_name": name,
                    "passed": rid not in refs,
                    "note": "模型未明确评估该项",
                }
            )

    # 兜底:note 里已列出缺陷/需人工核验,却仍被标「通过」的,降级为「需人工核验」,避免漏看问题项。
    for c in out:
        if c["passed"] is True and _note_has_problem(c["note"]):
            c["passed"] = None
    return out


def _agent_summary(a: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    if _str(a.get("name")):
        out["姓名"] = _str(a.get("name"))
    if _str(a.get("agent_auth")):
        out["委托权限"] = _str(a.get("agent_auth"))
    if _str(a.get("law_firm_name")):
        out["律师事务所"] = _str(a.get("law_firm_name"))
    return out


def _person_summary(p: dict) -> dict[str, Any]:
    return {
        "姓名": _str(p.get("name")),
        "性别": _str(p.get("sex")),
        "出生日期": _str(p.get("birth")),
        "身份证号": _str(p.get("id_number")),
        "手机": _str(p.get("mobile")),
        "户籍/住址": _str(p.get("registered_permanent_residence") or p.get("address")),
        "送达地址": _str(p.get("receive_address")),
        "身份证照片(正/反)": f"{_uploaded(p.get('card_image_front'))}/{_uploaded(p.get('card_image_reverse'))}",
        "代理人": [_agent_summary(a) for a in (p.get("agents") or []) if isinstance(a, dict)],
    }


def _company_summary(c: dict) -> dict[str, Any]:
    return {
        "名称": _str(c.get("name")),
        "统一社会信用代码": _str(c.get("social_code")),
        "法定代表人": _str(c.get("legal_name")),
        "住所/注册地址": _str(c.get("registered_address") or c.get("company_address")),
        "送达地址": _str(c.get("receive_address")),
        "证照照片(正/反)": f"{_uploaded(c.get('card_image_front'))}/{_uploaded(c.get('card_image_reverse'))}",
        "注册资本": _str(c.get("registered_capital")),
        "企业性质": _str(c.get("company_nature")),
        "代理人": [_agent_summary(a) for a in (c.get("agents") or []) if isinstance(a, dict)],
    }


def _request_summary(r: dict) -> dict[str, Any]:
    type_path = "/".join(
        _str(t.get("name")) for t in (r.get("type") or []) if isinstance(t, dict) and _str(t.get("name"))
    )
    start_at = _str(r.get("start_at"))
    end_at = _str(r.get("end_at"))
    period = None
    if start_at and end_at:
        period = f"{start_at} 至 {end_at}"
    elif start_at:
        period = f"{start_at} 起"
    elif end_at:
        period = f"至 {end_at}"
    return {
        "请求类型": type_path,
        "请求内容": _str(r.get("intro")),
        "金额(元)": _str(r.get("object")),
        "起止期间": period,
        "是否主要争议": _yesno(r.get("is_main_dispute")),
    }


def build_case_payload(detail: dict) -> dict[str, Any]:
    """把预约详情压成紧凑的结构化摘要(送进 user message 的 JSON)。"""
    cases = detail.get("cases") if isinstance(detail.get("cases"), dict) else {}
    position = "/".join(
        _str(p.get("name")) for p in (cases.get("position") or []) if isinstance(p, dict) and _str(p.get("name"))
    )
    fact = detail.get("case_fact_reason")
    fact = fact if isinstance(fact, dict) else {}
    return {
        "案件基本信息": {
            "案由": _str(cases.get("case_reason")),
            "申请来源": _str(cases.get("case_source")),
            "申请日期": _str(cases.get("apply_at")),
            "申请人类型": _str(cases.get("applicant_type")),
            "涉及人数": _str(cases.get("involve_number")),
            "是否签订劳动合同": _yesno(cases.get("is_sign_labor_contract")),
            "是否涉及劳务派遣": _yesno(cases.get("is_involve_labor_dispatch")),
            "地区(管辖)": position,
        },
        "申请人": [_person_summary(p) for p in (detail.get("applicant") or []) if isinstance(p, dict)],
        "被申请人": [_company_summary(c) for c in (detail.get("respondent") or []) if isinstance(c, dict)],
        "其他当事人": [_person_summary(p) for p in (detail.get("thirdpartys") or []) if isinstance(p, dict)],
        "共同代理人": [_agent_summary(a) for a in (detail.get("commonAgent") or []) if isinstance(a, dict)],
        "仲裁请求": [
            _request_summary(r) for r in (detail.get("case_arb_request") or []) if isinstance(r, dict)
        ],
        "事实与理由": {
            "内容": _str(fact.get("content")),
            "入职时间": _str(fact.get("entry_at")),
            "实际工作地": _str(fact.get("actual_workplace")),
            "岗位": _str(fact.get("job")),
            "工资标准": _str(fact.get("salary")),
            "是否签订劳动合同": _yesno(fact.get("is_sign_labor_contract")),
            "是否缴纳社保": _yesno(fact.get("is_pay_social_insurance")),
            "主要事由": _list(fact.get("main_cause")),
        },
        "证据材料": [
            {
                "名称": _str(m.get("name")),
                "证明对象": _str(m.get("object")),
                "证据类型": _str(m.get("type")),
                "材料形式": _str(m.get("material_type")),
                "页数": _str(m.get("pages")),
                "提交人": _str(m.get("submitter")),
            }
            for m in (detail.get("case_evidence_material") or [])
            if isinstance(m, dict)
        ],
    }


def build_messages(payload: dict[str, Any]) -> list[dict[str, str]]:
    """system = 审查规则提示词;user = 案件结构化摘要 JSON。"""
    return [
        {"role": "system", "content": RESERVE_REVIEW_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def parse_result(text: str) -> dict[str, Any]:
    """把模型输出解析为 {conclusion, reason, issues, missing_materials, rule_refs}。

    容忍 markdown ```json 围栏;解析失败/结论非法时降级为「审查失败」。
    """
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:].lstrip()
    start = t.find("{")
    end = t.rfind("}")
    if start == -1 or end < start:
        return failure_result("模型输出无法解析为 JSON")
    try:
        obj = json.loads(t[start : end + 1])
    except (ValueError, TypeError):
        return failure_result("模型输出无法解析为 JSON")
    if not isinstance(obj, dict):
        return failure_result("模型输出结构异常")

    conclusion = obj.get("conclusion")
    if conclusion not in _VALID_CONCLUSIONS:
        return failure_result("模型未给出合法的结论(通过/补正/驳回)")
    rule_refs = _list(obj.get("rule_refs"))
    return {
        "conclusion": conclusion,
        "reason": _str(obj.get("reason")) or "（模型未给出说明）",
        "issues": _list(obj.get("issues")),
        "missing_materials": _list(obj.get("missing_materials")),
        "rule_refs": rule_refs,
        "checks": _normalize_checks(obj, rule_refs),
    }
