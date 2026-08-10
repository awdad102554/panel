"""内网案件系统统计服务。

从内网案件系统按环节(收件 receive / 立案在办 handle)取总数,聚合成面板案件总览与
统计概览所需的计数。只读、实时拉取,不落库。

关键点:内网接口响应体自带总数字段 data.totalNum(见实测,GET .../arb/receive?page=1&
page_size=1 返回 data.totalNum),因此只需 page_size=1 的最小请求即可拿到总数,
不必把全量数据拉回来数——内网单条记录处理较慢,page_size=1000 级别的请求会超时。

reserve(庭前预约)环节接口要求额外必填参数(实测返回 422 "type 不能为空"),
当前未知其取值,故未接入;不影响 receive/handle 两个环节的统计。
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.integrations.case_system.client import (
    CaseSystemClient,
    CaseSystemError,
    get_case_system_client,
)

logger = logging.getLogger(__name__)

# 环节接口路径(GET,分页参数 page/page_size),对应内网 arb 各环节。
_STAGE_PATHS = {
    "receive": "/v1/api/admin/arb/receive",
    "handle": "/v1/api/admin/arb/handle",
}


class CaseSystemStatsService:
    def __init__(self, client: CaseSystemClient | None = None) -> None:
        self._client = client or get_case_system_client()

    async def _fetch_stage_total(self, stage: str) -> int:
        """只取该环节的记录总数(data.totalNum),不拉取明细列表。"""
        path = _STAGE_PATHS[stage]
        resp = await self._client.get(path, params={"page": 1, "page_size": 1})
        if resp.status_code != 200:
            raise CaseSystemError(f"{stage}_http_{resp.status_code}")
        try:
            body = resp.json()
        except (ValueError, httpx.HTTPError) as exc:
            raise CaseSystemError(f"{stage}_parse_failed: {exc}") from exc

        data = body.get("data") if isinstance(body, dict) else None
        total = data.get("totalNum") if isinstance(data, dict) else None
        if not isinstance(total, int):
            raise CaseSystemError(f"{stage}_missing_total")
        return total

    async def _fetch_all_totals(self) -> dict[str, int]:
        stages = list(_STAGE_PATHS)
        results = await asyncio.gather(
            *(self._fetch_stage_total(s) for s in stages),
            return_exceptions=True,
        )
        out: dict[str, int] = {}
        for stage, result in zip(stages, results):
            if isinstance(result, CaseSystemError):
                # 单个环节失败不致命:记录并当作 0,其余环节仍可统计。
                logger.warning("内网环节 %s 取总数失败: %s", stage, result)
                out[stage] = 0
            elif isinstance(result, BaseException):
                raise result
            else:
                out[stage] = result
        if all(v == 0 for v in out.values()):
            # 所有环节都失败/为 0,视为内网整体不可用,交给上层回退本地。
            raise CaseSystemError("all_stages_empty")
        return out

    async def fetch_dashboard_summary(self) -> dict[str, int]:
        """对应 /dashboard/summary:各环节总数映射到案件总览字段。

        口径已与用户确认:
        - pending_filing(待立案) = receive 环节总数(收件数)。
        - filed_awaiting_hearing(已立案待开庭) = handle 环节总数(立案数)。
          注意这是"立案总数",不会剔除其中已经开庭/裁决完的案子——内网接口的
          status 字段含义摸不准(不同环节、不同取值表现不一致),暂不按开庭子状态
          再筛一道,按确认口径直接用环节总数。
        """
        totals = await self._fetch_all_totals()
        return {
            "pending_filing": totals.get("receive", 0),  # 待立案 = 收件数
            "filed_awaiting_hearing": totals.get("handle", 0),  # 已立案待开庭 = 立案数
        }
