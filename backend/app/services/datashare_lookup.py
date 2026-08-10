"""查自然人/查企业:直连内网数据共享接口(与 InfoWeb 同一套上游,不再依赖 InfoWeb 在线)。

上游是内网案件系统同主机(10.96.10.78:8080)的数据共享代理接口,认证复用
CaseSystemClient 的登录/token 管理:
- 自然人: POST datashare/openPlatformProxy/api/SJCK_idCardInfo {"AAC147": 身份证号}
- 企业:   POST datashare/openPlatformProxy/api/SJCK_businessFiveCertInfo
          按名称 {"CNNAME": 名称}(服务端可能返回多条,本地再做精确/模糊过滤)
          按信用代码 {"TYSHXYDM": 代码}

字段中文映射与 InfoWeb modules/company_query.py 的 format 保持一致。
"""

from __future__ import annotations

import logging
from datetime import datetime

from app.integrations.case_system.client import (
    CaseSystemClient,
    CaseSystemError,
    get_case_system_client,
)

logger = logging.getLogger(__name__)

_PERSON_PATH = "/v1/api/admin/datashare/openPlatformProxy/api/SJCK_idCardInfo"
_COMPANY_PATH = "/v1/api/admin/datashare/openPlatformProxy/api/SJCK_businessFiveCertInfo"

# 企业字段 → 中文(与 InfoWeb format_company_info 一致)。
_COMPANY_FIELDS = {
    "CNNAME": "企业名称",
    "TYSHXYDM": "统一社会信用代码",
    "REGADDRESS": "注册地址",
    "SCJYDZ": "实际经营地址",
    "LEGALPERSONNAME": "法人姓名",
    "COMPANYPHONE": "公司电话",
    "COMPANYTYPE": "公司类型",
    "QYTYPE": "企业类型",
    "REGISTERSTATE": "注册状态",
    "REGFUNDAMOUNT": "注册资本（万元）",
    "ESTABLISHDATE": "成立日期",
    "GSZCH": "工商注册号",
}


def _format_company(item: dict) -> dict:
    out: dict = {}
    for key, cn in _COMPANY_FIELDS.items():
        value = item.get(key)
        if value is None:
            continue
        if key == "ESTABLISHDATE" and isinstance(value, int):
            try:
                value = datetime.fromtimestamp(value / 1000).strftime("%Y-%m-%d")
            except (ValueError, OSError):
                pass
        out[cn] = value
    return out


# 自然人字段 → 中文(内网 SJCK_idCardInfo 返回的是人社数据码值,
# 与 InfoWeb handle-query.js renderIdcardResult 的映射一致)。
_PERSON_FIELDS = {
    "AAC003": "姓名",
    "AAC004": "性别",
    "AAC005": "民族",
    "AAC006": "出生日期",
    "AAC147": "身份证号码",
    "AAE006": "户籍地址",
}


def _format_person(item: dict) -> dict:
    out = {cn: item[key] for key, cn in _PERSON_FIELDS.items() if item.get(key) is not None}
    return out or item  # 码值都不认识时退回原始字段,前端兜底展示


async def _post_json(client: CaseSystemClient, path: str, payload: dict) -> dict | None:
    """POST 内网接口并返回 body;非 200 抛 CaseSystemError,非 JSON/业务 code!=200
    记日志并返回 None(按"未查到"处理,避免结构异常冒成 500)。"""
    resp = await client.post(path, json=payload)
    if resp.status_code != 200:
        raise CaseSystemError(f"{path.rsplit('/', 1)[-1]}_http_{resp.status_code}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise CaseSystemError(f"bad_json: {exc}") from exc
    if not isinstance(body, dict):
        return None
    if body.get("code") != 200:
        logger.warning("内网查询业务错误: %s", str(body)[:200])
        return None
    return body


async def lookup_person(id_card: str, client: CaseSystemClient | None = None) -> dict | None:
    """按身份证号查自然人,返回中文字段 dict;查不到返回 None。

    注意内网查不到时也返回 code=200,但 data 是空列表,需判空。
    """
    client = client or get_case_system_client()
    body = await _post_json(client, _PERSON_PATH, {"AAC147": id_card})
    if body is None:
        return None
    data = body.get("data")
    # 内网未命中时返回 {"data": [], ...}(code 仍是 200);命中时内层 data 是
    # 人员信息列表。统一取内层第一条,空则 None。
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        items = [i for i in data["data"] if isinstance(i, dict)]
        return _format_person(items[0]) if items else None
    if not data or (isinstance(data, list) and len(data) == 0):
        return None
    if isinstance(data, dict):
        return _format_person(data)
    return None


async def lookup_company(
    name: str, client: CaseSystemClient | None = None, exact_match: bool = False
) -> list[dict]:
    """按名称查企业,返回格式化(中文字段)列表;查不到返回空列表。

    内网 CNNAME 查询只认完整名称(部分名称返回空);输入形如 18 位统一社会
    信用代码时自动改用 TYSHXYDM 通道查一次。
    """
    client = client or get_case_system_client()
    items = await _query_company_by(client, {"CNNAME": name}, name, exact_match)
    if not items and len(name.strip()) == 18:
        code = name.strip()
        items = await _query_company_by(client, {"TYSHXYDM": code}, code, exact_match=True)
    return items


async def _query_company_by(
    client: CaseSystemClient, payload: dict, keyword: str, exact_match: bool
) -> list[dict]:
    body = await _post_json(client, _COMPANY_PATH, payload)
    if body is None:
        return []
    data = body.get("data") or []
    if not isinstance(data, list):
        return []
    key = "TYSHXYDM" if "TYSHXYDM" in payload else "CNNAME"
    if exact_match:
        data = [i for i in data if isinstance(i, dict) and i.get(key) == keyword]
    else:
        data = [i for i in data if isinstance(i, dict) and keyword in (i.get(key) or "")]
    return [_format_company(i) for i in data]
