"""预约「审核结果」提交内网(preAudit)。

把工作人员确认的「同意/不同意 + 8 选 1 理由 + 补充说明」组装成内网预约审核请求体,
PUT 到 `/v1/api/admin/arb/{reserve_row_id}/reserve/preAudit`,成功后落库留痕(见端点)。

内网请求体(工作人员点击审核后产生的真实样例,2026-08):
    PUT /v1/api/admin/arb/{reserve_row_id}/reserve/preAudit
    {"reason": "其他:1.…；2.…；…", "status": 2}

注意方法是 PUT 不是 POST:2026-08-28 实测内网(Symfony)对该路由只支持 PUT,
POST 返回 405 "Supported methods: PUT"(早期抓包样例误记为 POST,已修正)。

口径(与用户确认):
- 同意(通过)      → {"reason": "", "status": 1}(内网无通过样本,reason 留空)。
- 不同意(补正/驳回) → {"reason": <组合>, "status": 2};其中「请补正」「其他」= `理由:逐条明细`,
  其余 6 条长句理由直接原文、不加冒号。
- 内网 status 枚举:0 待审核 / 1 通过 / 2 不通过 / 3 现场同意 / 4 现场不同意;补正与驳回都走 2。
"""

from __future__ import annotations

import logging
from typing import Any

from app.integrations.case_system.client import (
    CaseSystemError,
    get_case_system_client,
)
from app.schemas.reserve_review import REJECT_REASONS_NEED_DETAIL

logger = logging.getLogger(__name__)

PREAUDIT_PATH = "/v1/api/admin/arb/{reserve_row_id}/reserve/preAudit"

# 内网 reason 字段长度上限(2026-08-28 实测:"reason 长度不能大于 255 个字符")。
# 超限会被内网 422 拒绝,故提交前先本地校验,给调用方明确的精简提示。
MAX_REASON_LEN = 255


def compose_preaudit_payload(
    decision: str,
    reject_reason: str | None,
    reject_detail: str | None,
) -> dict[str, Any]:
    """把人工审核决定组装成内网 preAudit 请求体(纯函数,便于单测)。

    同意 → {"reason": "", "status": 1};不同意 → {"reason": <组合>, "status": 2}。
    不同意且理由为「请补正」「其他」时 reason = `理由:明细`;其余长句理由原文;
    reject_reason 漏给兜底「其他」。
    """
    if decision == "同意":
        return {"reason": "", "status": 1}
    if reject_reason in REJECT_REASONS_NEED_DETAIL:
        return {"reason": f"{reject_reason}:{reject_detail or ''}", "status": 2}
    return {"reason": reject_reason or "其他", "status": 2}


async def submit_decision_to_internal(
    reserve_row_id: int,
    decision: str,
    reject_reason: str | None,
    reject_detail: str | None,
) -> dict[str, Any]:
    """组装并 POST 到内网 preAudit,成功返回 body.data(可能为空 dict)。

    失败抛 CaseSystemError(HTTP 非 200 / 非 JSON / code 非 200 或 0),由端点转 502,
    不伪造成功——提交失败即不落库,前端表单保留可重试。
    """
    payload = compose_preaudit_payload(decision, reject_reason, reject_detail)
    if len(payload["reason"]) > MAX_REASON_LEN:
        raise ValueError(
            f"理由+明细共 {len(payload['reason'])} 字，超过内网 {MAX_REASON_LEN} 字上限，请精简明细后重试"
        )
    client = get_case_system_client()
    path = PREAUDIT_PATH.format(reserve_row_id=reserve_row_id)
    # 内网该路由只支持 PUT(POST 返回 405,2026-08-28 实测)。
    resp = await client.put(path, json=payload)
    if resp.status_code != 200:
        raise CaseSystemError(f"preAudit http_{resp.status_code}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise CaseSystemError(f"preAudit 返回非 JSON: {resp.text[:200]}") from exc
    if body.get("code") not in (200, 0):
        raise CaseSystemError(
            f"内网预约审核失败: {body.get('message') or str(body)[:200]}"
        )
    logger.info(
        "预约审核结果已提交内网 row_id=%s status=%s", reserve_row_id, payload["status"]
    )
    return body.get("data") or {}
