"""预登记案件提交到内网收件(POST /v1/api/admin/arb/receive/add)。

请求体结构来自内网"智慧调解仲裁系统"新建收案件的抓包样例(2026-08-11),字典类数据
全部从内网接口实时拉取并做内存缓存(单 worker,变动极少):
- 仲裁请求三级类型树:  GET /v1/api/admin/norm/arbRequest
- 请求第四级选项+模板: GET /v1/api/admin/norm/arbRequest/{叶子id}
- 通用字典(案由/企业性质等): GET /v1/api/admin/norm/byType?type={key}
- 乡镇街道: GET /v1/api/common/get_structure_towns

仲裁请求的类型树无法从自由文本自动推断,采用"关键词猜 + 人工确认"(2026-08-11 用户确认):
submit-draft 给出猜测,前端对话框里用户确认/修改后 submit 正式提交。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

from app.integrations.case_system.client import (
    CaseSystemError,
    get_case_system_client,
)
from app.services.datashare_lookup import lookup_company

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------- 字典缓存

_CACHE_TTL = 6 * 3600  # 字典变动极少,进程内缓存 6 小时
_cache: dict[str, tuple[float, Any]] = {}


async def _cached(key: str, loader):
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _CACHE_TTL:
        return hit[1]
    data = await loader()
    _cache[key] = (time.monotonic(), data)
    return data


async def _get_json(path: str) -> Any:
    client = get_case_system_client()
    resp = await client.get(path)
    if resp.status_code != 200:
        raise CaseSystemError(f"{path} http_{resp.status_code}")
    body = resp.json()
    if body.get("code") != 200:
        raise CaseSystemError(f"{path} code={body.get('code')}")
    return body.get("data")


async def get_arb_tree() -> list[dict]:
    """仲裁请求三级类型树。[{id,code,name,data:[二级],...}]"""
    return await _cached("arb_tree", lambda: _get_json("/v1/api/admin/norm/arbRequest"))


async def get_request_leaf(leaf_id: int) -> dict:
    """叶子节点详情:{template, arr:[[第四级选项...]], other}。"""
    return await _cached(
        f"arb_leaf_{leaf_id}", lambda: _get_json(f"/v1/api/admin/norm/arbRequest/{leaf_id}")
    )


async def get_norm_dict(type_key: str) -> list[dict]:
    """通用字典:[{id,name,value,...}]。"""
    return await _cached(
        f"norm_{type_key}", lambda: _get_json(f"/v1/api/admin/norm/byType?type={type_key}")
    )


async def get_towns() -> list[dict]:
    """本区县乡镇街道:[{town_id, town_name, county_id}]。"""
    return await _cached("towns", lambda: _get_json("/v1/api/common/get_structure_towns"))


async def get_request_catalog() -> list[dict]:
    """全部叶子的(路径, 第四级选项, 模板)目录,供关键词猜测与前端级联选择。"""
    cached = _cache.get("arb_catalog")
    if cached and time.monotonic() - cached[0] < _CACHE_TTL:
        return cached[1]
    tree = await get_arb_tree()
    leaves: list[tuple[dict, dict, dict]] = []  # (l1, l2, l3)
    for l1 in tree:
        for l2 in l1.get("data") or l1.get("children") or []:
            for l3 in l2.get("data") or l2.get("children") or []:
                leaves.append((l1, l2, l3))
    details = await asyncio.gather(
        *(get_request_leaf(l3["id"]) for _, _, l3 in leaves), return_exceptions=True
    )
    catalog: list[dict] = []
    for (l1, l2, l3), detail in zip(leaves, details):
        if isinstance(detail, Exception):
            logger.warning("仲裁请求叶子详情拉取失败 id=%s: %s", l3["id"], detail)
            detail = {}
        options = (detail.get("arr") or [[]])[0] or []
        catalog.append(
            {
                "path": [
                    {"id": l1["id"], "code": l1.get("code", ""), "name": l1["name"]},
                    {"id": l2["id"], "code": l2.get("code", ""), "name": l2["name"]},
                    {"id": l3["id"], "code": l3.get("code", ""), "name": l3["name"]},
                ],
                "options": options,
                "template": detail.get("template") or "",
            }
        )
    _cache["arb_catalog"] = (time.monotonic(), catalog)
    return catalog


# ---------------------------------------------------------------- 常量与默认值

# 本院管辖固定为 福建省/三明市/永安市(编码来自 /v1/api/common/area 实测)。
DEFAULT_POSITION = [
    {"Id": 350, "name": "福建省"},
    {"Id": 350400000000, "name": "三明市"},
    {"Id": 350481000000, "name": "永安市"},
]
DEFAULT_TOWN_ID = 350481001000  # 燕东街道
DEFAULT_ID_TYPE = "居民身份证（户口簿）"
DEFAULT_CASE_SOURCE = "申请人窗口申请"
DEFAULT_APPLICANT_TYPE = "劳动者"
DEFAULT_COMPANY_NATURE = "私营企业"
SUBMIT_PATH = "/v1/api/admin/arb/receive/add"

# 内网"您本次申请劳动仲裁的最主要原因"预设选项(2026-08-11 内网编辑页截图核对;
# 该列表不在任何字典接口里,为内网前端写死)。勾选其他时为 [None, 自定义文本](样例1)。
MAIN_CAUSE_PRESETS = [
    "被申请人拒绝确认与本人劳动关系，请求确认双方存在劳动关系",
    "被申请人未与本人签订书面劳动合同",
    "被申请人未及时足额支付劳动报酬",
    "被申请人违反劳动合同约定，申请人请求解除劳动关系并要求被申请人支付经济补偿",
    "被申请人违法解除与申请人劳动关系，请求支付赔偿金",
    "申请人负工伤，被申请人拒绝支付工伤保险待遇",
]


# ---------------------------------------------------------------- 输入模型


class RequestItem(BaseModel):
    """第四级选项+单项金额(多选项请求,如工伤保险待遇的各费用项,样例2)。"""

    name: str
    object: float | None = None


class RequestSpec(BaseModel):
    """一条仲裁请求的提交参数(path_ids 为三级类型树节点 id)。

    单选项请求用 option+object;多选项请求($str 模板,如工伤保险待遇)用 items,
    object 为空时自动按 items 求和。"""

    text: str  # 预登记原始自由文本(兜底 intro)
    path_ids: list[int]  # [一级id, 二级id, 三级id]
    option: str | None = None  # 第四级选项(无金额类请求可为空)
    object: float | None = None  # 标的金额(确认劳动关系等无金额请求为空)
    items: list[RequestItem] = []  # 多选项明细(优先级高于 option)
    intro: str | None = None  # 请求表述;为空时按模板自动生成,生成不了退回 text


class SubmitSpec(BaseModel):
    apply_at: date
    town_id: int = DEFAULT_TOWN_ID
    case_reason: str
    is_sign_labor_contract: int = 1
    is_pay_social_insurance: int = 1
    is_easy: int = 1  # 是否简易案件(样例1小额=1/样例2工伤20万=0,规则不明,界面可改)
    company_nature: str = DEFAULT_COMPANY_NATURE
    # 主要原因(进 fact_reason.main_cause 与事实理由"因…"段):预设文本原样,
    # 非预设视为"其他"自定义文本(内网结构 [None, 自定义],样例1)。
    main_causes: list[str] = []
    fact_content: str | None = None  # 事实理由全文(用户编辑版;为空则自动生成/用预登记 facts)
    requests: list[RequestSpec]


def compose_facts(
    first: dict,
    is_sign_labor_contract: int,
    is_pay_social_insurance: int,
    main_causes: list[str] | None = None,
) -> str:
    """按内网"自动生成事实理由"的模板拼接(来自内网前端 getContent,样例2 验证)。

    模板:本人于X年X月X日入职被申请人处, 实际工作地点…，工作岗位为…，月工资标准为…元。
    本人入职后，被申请人{有/没有}与本人签订书面劳动合同,{有/没有}为本人缴纳社会保险费;
    因{main_causes.join("，")}。为维护本人合法权益，特提出申请，望裁如所请。
    缺字段的片段自动省略,不出现"None/空"字样。
    """
    parts: list[str] = []
    entry = _to_date_str(first.get("entry_date"))
    if entry:
        y, m, d = entry.split("-")
        seg = f"本人于{int(y)}年{int(m)}月{int(d)}日入职被申请人处"
        tail: list[str] = []
        if first.get("work_place"):
            tail.append(f"实际工作地点{first['work_place']}")
        if first.get("position"):
            tail.append(f"工作岗位为{first['position']}")
        if _to_float(first.get("monthly_wage")) is not None:
            tail.append(f"月工资标准为{_fmt_amount(_to_float(first['monthly_wage']))}元")
        if tail:
            seg += ", " + "，".join(tail)
        parts.append(seg + "。")
    sign = "有" if is_sign_labor_contract == 1 else "没有"
    ins = "有" if is_pay_social_insurance == 1 else "没有"
    parts.append(f"本人入职后，被申请人{sign}与本人签订书面劳动合同,{ins}为本人缴纳社会保险费")
    cause = "，".join(c.strip() for c in (main_causes or []) if c and c.strip())
    if cause:
        parts[-1] += f";因{cause}。"
    else:
        parts[-1] += "。"
    parts.append("为维护本人合法权益，特提出申请，望裁如所请。")
    return "".join(parts)


def _main_cause_array(main_causes: list[str]) -> list:
    """组装 fact_reason.main_cause:预设原样入列;"其他"自定义文本按内网结构
    表示为 [None, 文本](样例1)。空列表退回 [None, ""]。"""
    presets = [c for c in main_causes if c in MAIN_CAUSE_PRESETS]
    customs = [c.strip() for c in main_causes if c not in MAIN_CAUSE_PRESETS and c.strip()]
    out: list = list(presets)
    if customs:
        out += [None, "；".join(customs)]
    return out or [None, ""]


# ---------------------------------------------------------------- 关键词猜测

_AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*元")


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def guess_request(text: str, catalog: list[dict]) -> dict | None:
    """按关键词在请求目录里猜(叶子路径, 第四级选项);猜不中返回 None。

    评分:选项/叶子名是文本子串得全长分;文本是选项子串打 8 折。优先比选项(更具体)。
    """
    t = _norm_text(text)
    if not t:
        return None
    best: tuple[float, dict, str | None] | None = None

    def score(keyword: str, weight: float) -> float:
        k = _norm_text(keyword)
        if not k:
            return 0.0
        if k in t:
            return len(k) * weight
        if t in k:
            return len(t) * 0.8 * weight
        return 0.0

    for item in catalog:
        leaf_name = item["path"][-1]["name"]
        for opt in item["options"]:
            s = score(opt, 1.0)
            if s and (best is None or s > best[0]):
                best = (s, item, opt)
        s = score(leaf_name, 0.9)
        if s and (best is None or s > best[0]):
            best = (s, item, None)
    if best is None:
        return None
    _, item, option = best
    return {
        "path_ids": [n["id"] for n in item["path"]],
        "path_names": [n["name"] for n in item["path"]],
        "option": option,
    }


def guess_amount(text: str, option: str | None) -> float | None:
    """从自由文本猜标的金额:优先取匹配选项之后最近的"N元",否则取第一个。"""
    t = _norm_text(text)
    start = t.find(_norm_text(option)) if option else -1
    seg = t[start:] if start >= 0 else t
    m = _AMOUNT_RE.search(seg)
    if m is None and start >= 0:
        m = _AMOUNT_RE.search(t)
    return float(m.group(1)) if m else None


# ---------------------------------------------------------------- 请求体组装


def _fmt_amount(value: float) -> str:
    """金额格式化:不能用 %g(6 位有效数字会截断 53015.63→53015.6)。"""
    s = f"{value:.2f}".rstrip("0").rstrip(".")
    return s


def _fill_template(
    template: str,
    option: str | None,
    obj: float | None,
    items: list[RequestItem] | None = None,
) -> str | None:
    """按内网模板生成请求表述。含无法填充的占位时返回 None。

    $str 模板(样例2 工伤保险待遇):$str 替换为"（1）选项名金额元、（2）…"枚举,
    需要 items 且每项有金额。
    """
    if not template:
        return None
    out = template
    if "$str" in out:
        if not items or any(i.object is None for i in items):
            return None
        enum = "、".join(
            f"（{n}）{i.name}{_fmt_amount(i.object)}元"
            for n, i in enumerate(items, start=1)
        )
        out = out.replace("$str", enum)
    if "选项2" in out:
        return None
    if "选项1" in out:
        if not option:
            return None
        out = out.replace("选项1", option)
    if "标的" in out:
        if obj is None:
            return None
        out = out.replace("标的", _fmt_amount(obj))
    if not out.endswith("。"):
        out += "。"
    return out


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _to_date_str(value: Any) -> str | None:
    if not value:
        return None
    s = str(value).strip()[:10]
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None
    return s


def validate_case(case: dict) -> tuple[list[str], list[str]]:
    """提交前校验。返回 (errors, warnings);有 errors 不允许提交。"""
    errors: list[str] = []
    warnings: list[str] = []
    applicants = case.get("applicants") or []
    respondents = case.get("respondents") or []
    if not applicants:
        errors.append("缺少申请人")
    if not respondents:
        errors.append("缺少被申请人")
    for p in applicants:
        name = p.get("name") or "?"
        if not p.get("id_number"):
            errors.append(f"申请人[{name}]缺少身份证号")
        for field, label in (
            ("phone", "联系电话"),
            ("address", "户籍地址"),
            ("birth_date", "出生日期"),
            ("gender", "性别"),
        ):
            if not p.get(field):
                warnings.append(f"申请人[{name}]缺少{label}")
    for p in respondents:
        name = p.get("name") or "?"
        if p.get("party_type") == "company":
            if not p.get("id_number"):
                warnings.append(f"被申请人[{name}]缺少统一社会信用代码")
            if not p.get("address"):
                warnings.append(f"被申请人[{name}]缺少地址")
        elif not p.get("id_number"):
            warnings.append(f"被申请人[{name}]缺少身份证号")
    has_request = any(p.get("requests") for p in applicants) or case.get("claims")
    if not has_request:
        errors.append("缺少仲裁请求")
    return errors, warnings


def build_payload(case: dict, spec: SubmitSpec, catalog: list[dict]) -> dict:
    """把预登记案件 + 用户确认的请求类型组装成内网 receive/add 请求体。"""
    applicants = case.get("applicants") or []
    respondents = case.get("respondents") or []

    personals: list[dict] = []
    for i, p in enumerate(applicants):
        personals.append(
            {
                "name": p.get("name"),
                "sex": p.get("gender") or "男",
                "nation": p.get("ethnicity") or "汉族",
                "birth": _to_date_str(p.get("birth_date")),
                "is_migrant_worker": 0,
                "id_type": DEFAULT_ID_TYPE,
                "id_number": p.get("id_number"),
                "mobile": p.get("phone"),
                "is_three_woman_worker": 0,
                "registered_permanent_residence": p.get("address"),
                "role": 1,
                "related_user_type": 1,
                "sort": i + 1,
            }
        )
    # 自然人被申请人也进 personals(role=2)。
    for i, p in enumerate([r for r in respondents if r.get("party_type") != "company"]):
        personals.append(
            {
                "name": p.get("name"),
                "sex": p.get("gender") or "男",
                "nation": p.get("ethnicity") or "汉族",
                "birth": _to_date_str(p.get("birth_date")),
                "is_migrant_worker": 0,
                "id_type": DEFAULT_ID_TYPE,
                "id_number": p.get("id_number"),
                "mobile": p.get("phone"),
                "is_three_woman_worker": 0,
                "registered_permanent_residence": p.get("address"),
                "role": 2,
                "related_user_type": 2,
                "sort": i + 1,
            }
        )

    companys: list[dict] = []
    for i, p in enumerate([r for r in respondents if r.get("party_type") == "company"]):
        companys.append(
            {
                "name": p.get("name"),
                "registered_capital": _to_float(p.get("registered_capital")),
                "company_nature": p.get("company_nature") or spec.company_nature,
                "belong_to_industry": [],
                "social_code": p.get("id_number"),
                "legal_type": 1,
                "legal_name": p.get("legal_person"),
                "legal_job": p.get("legal_title"),
                "mobile": p.get("phone"),
                "company_address": p.get("address"),
                "role": 2,
                "related_user_type": 2,
                "sort": i + 1,
            }
        )

    by_leaf = {item["path"][-1]["id"]: item for item in catalog}
    arb_requests: list[dict] = []
    for req in spec.requests:
        if len(req.path_ids) != 3:
            raise ValueError(f"仲裁请求类型路径必须是三级: {req.text[:20]}")
        leaf = by_leaf.get(req.path_ids[-1])
        if leaf is None:
            raise ValueError(f"仲裁请求类型不存在(id={req.path_ids[-1]}): {req.text[:20]}")
        option_names = [o for o in leaf["options"]]
        if req.items:
            bad = [i.name for i in req.items if i.name not in option_names]
            if bad:
                raise ValueError(f"第四级选项不在字典中: {'、'.join(bad)}")
        elif req.option and req.option not in option_names:
            raise ValueError(f"第四级选项不在字典中: {req.option}")

        # 多选项($str 模板):object 为空时按各项金额求和(样例2 工伤待遇)。
        obj = req.object
        if req.items and obj is None:
            amounts = [i.object for i in req.items if i.object is not None]
            obj = sum(amounts) if amounts else None
        names = [i.name for i in req.items] if req.items else ([req.option] if req.option else [])
        level4_arr = (
            [{"name": i.name, "object": i.object} for i in req.items]
            if req.items
            else ([{"name": req.option, "object": obj}] if req.option else [])
        )
        intro = (
            req.intro
            or _fill_template(leaf["template"], req.option, obj, req.items or None)
            or req.text
        )
        arb_requests.append(
            {
                "type": leaf["path"],
                "is_main_dispute": 0,
                "object": obj,
                "intro": intro,
                "opt": [names],
                "level4_arr": level4_arr,
                "other": {},
            }
        )

    first = applicants[0] if applicants else {}
    facts = (spec.fact_content or "").strip()
    if not facts:
        facts = "；".join(
            f.strip() for f in (p.get("facts") for p in applicants) if f and f.strip()
        )
    if not facts:
        facts = compose_facts(
            first, spec.is_sign_labor_contract, spec.is_pay_social_insurance, spec.main_causes
        )
    main_cause = _main_cause_array(spec.main_causes)
    return {
        "case_info": {
            "case_reason": spec.case_reason,
            "case_source": DEFAULT_CASE_SOURCE,
            "applicant_type": DEFAULT_APPLICANT_TYPE,
            "apply_at": spec.apply_at.isoformat(),
            "is_team": 0,
            "involve_number": max(len(applicants), 1),
            "is_sign_labor_contract": spec.is_sign_labor_contract,
            "is_involve_labor_dispatch": 0,
            "position": DEFAULT_POSITION,
            "town_id": spec.town_id,
            "arb_type": 1,
            "is_easy": spec.is_easy,
            "new_business": 0,
            "platform": 0,
            "sentry_type": 0,
            "is_speed_arb": 0,
        },
        "personals": personals,
        "companys": companys,
        "arb_requests": arb_requests,
        "fact_reason": {
            "entry_at": _to_date_str(first.get("entry_date")),
            # 样例2:工作地点/岗位也进 fact_reason(预登记本就有这两个字段)。
            "actual_workplace": first.get("work_place"),
            "job": first.get("position"),
            "otherjob": first.get("position"),
            "salary": _to_float(first.get("monthly_wage")),
            "is_sign_labor_contract": spec.is_sign_labor_contract,
            "is_pay_social_insurance": spec.is_pay_social_insurance,
            "main_cause": main_cause,
            "content": facts,
            "otherIndex": 0,
            "otherChecked": True,
        },
        "evidence_materials": [],
        "materials": [],
        "receive_info": {"next_step": 1, "application_at": spec.apply_at.isoformat()},
        "case_med_doc": {},
        "speed_arb_factor": [],
    }


# ---------------------------------------------------------------- 草稿与提交


async def _fill_company_info(applicants: list[dict], respondents: list[dict]) -> list[dict]:
    """企业信息回填(查企业接口):注册资本/信用代码/法人/地址,填不上的留给人工。

    submit-draft 与 submit 共用:草稿展示回填结果,正式提交时必须重新回填
    (草稿的修改不落库,提交时重新从 DB 读)。
    """
    fills: list[dict] = []
    for p in respondents:
        if p.get("party_type") != "company" or not p.get("name"):
            continue
        fill = {"name": p["name"], "found": False}
        try:
            items = await lookup_company(p["name"], exact_match=True)
        except CaseSystemError as exc:
            logger.warning("查企业回填失败[%s]: %s", p["name"], exc)
            items = []
        if items:
            info = items[0]
            fill["found"] = True
            if not p.get("registered_capital") and info.get("注册资本（万元）"):
                p["registered_capital"] = info["注册资本（万元）"]
            if not p.get("id_number") and info.get("统一社会信用代码"):
                p["id_number"] = info["统一社会信用代码"]
            if not p.get("legal_person") and info.get("法人姓名"):
                p["legal_person"] = info["法人姓名"]
            if not p.get("address") and info.get("注册地址"):
                p["address"] = info["注册地址"]
            fill["registered_capital"] = p.get("registered_capital")
        fills.append(fill)
    return fills


async def build_draft(case: dict) -> dict:
    """submit-draft:自动猜测 + 企业信息回填 + 校验,供前端对话框展示/修改。"""
    catalog, towns, case_reasons, company_natures = await asyncio.gather(
        get_request_catalog(),
        get_towns(),
        get_norm_dict("case_reason"),
        get_norm_dict("company_nature"),
    )
    applicants = [dict(p) for p in case.get("applicants") or []]
    respondents = [dict(p) for p in case.get("respondents") or []]

    requests_draft: list[dict] = []
    for p in applicants:
        for text in p.get("requests") or []:
            guess = guess_request(text, catalog) or {}
            option = guess.get("option")
            requests_draft.append(
                {
                    "text": text,
                    "path_ids": guess.get("path_ids"),
                    "path_names": guess.get("path_names"),
                    "option": option,
                    "object": guess_amount(text, option),
                    "intro": None,
                    "guessed": bool(guess),
                }
            )
    # 旧版单一 claims 兼容:没有 requests 时按一条自由文本请求处理。
    if not requests_draft and case.get("claims"):
        requests_draft.append(
            {
                "text": case["claims"],
                "path_ids": None,
                "path_names": None,
                "option": None,
                "object": guess_amount(case["claims"], None),
                "intro": None,
                "guessed": False,
            }
        )

    # 企业信息回填(查企业接口),填不上的留给人工。
    company_fills = await _fill_company_info(applicants, respondents)

    merged = {**case, "applicants": applicants, "respondents": respondents}
    errors, warnings = validate_case(merged)

    # 事实理由:预登记有 facts 用原文,否则按内网模板自动生成(对话框可改/重新生成)。
    first = applicants[0] if applicants else {}
    existing_facts = "；".join(
        f.strip() for f in (p.get("facts") for p in applicants) if f and f.strip()
    )
    fact_content = existing_facts or compose_facts(first, 1, 1)
    for r in requests_draft:
        if not r["guessed"]:
            warnings.append(f"仲裁请求未能自动匹配类型,请人工选择: {r['text'][:30]}")

    # 案由默认值:优先案件已填且能在字典里精确/模糊匹配的值。
    case_reason = case.get("case_reason") or ""
    dict_names = [d["name"] for d in case_reasons]
    if case_reason and case_reason not in dict_names:
        case_reason = next(
            (n for n in dict_names if case_reason and (case_reason in n or n in case_reason)),
            "",
        )

    return {
        "defaults": {
            "apply_at": date.today().isoformat(),
            "town_id": DEFAULT_TOWN_ID,
            "case_reason": case_reason,
            "is_sign_labor_contract": 1,
            "is_pay_social_insurance": 1,
            "is_easy": 1,
            "company_nature": DEFAULT_COMPANY_NATURE,
            "position": DEFAULT_POSITION,
        },
        "requests": requests_draft,
        "respondents": respondents,
        "company_fills": company_fills,
        "fact_content": fact_content,
        "fact_parts": {
            "entry_date": first.get("entry_date"),
            "work_place": first.get("work_place"),
            "position": first.get("position"),
            "monthly_wage": first.get("monthly_wage"),
        },
        "errors": errors,
        "warnings": warnings,
        "meta": {
            "towns": towns,
            "case_reasons": dict_names,
            "company_natures": [d["name"] for d in company_natures],
            "catalog": catalog,
            "main_cause_presets": MAIN_CAUSE_PRESETS,
        },
    }


async def submit_case(case: dict, spec: SubmitSpec) -> dict:
    """组装并 POST 到内网收件;返回内网响应 data。业务失败抛 CaseSystemError。"""
    catalog = await get_request_catalog()
    applicants = [dict(p) for p in case.get("applicants") or []]
    respondents = [dict(p) for p in case.get("respondents") or []]
    await _fill_company_info(applicants, respondents)
    case = {**case, "applicants": applicants, "respondents": respondents}
    errors, _warnings = validate_case(case)
    if errors:
        raise ValueError("；".join(errors))
    try:
        payload = build_payload(case, spec, catalog)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"请求体组装失败: {exc}") from exc

    client = get_case_system_client()
    resp = await client.post(SUBMIT_PATH, json=payload)
    if resp.status_code != 200:
        raise CaseSystemError(f"receive/add http_{resp.status_code}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise CaseSystemError(f"receive/add 返回非 JSON: {resp.text[:200]}") from exc
    if body.get("code") != 200:
        raise CaseSystemError(f"内网收件失败: {body.get('message') or str(body)[:200]}")
    return body.get("data") or {}
