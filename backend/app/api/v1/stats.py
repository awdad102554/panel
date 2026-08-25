"""统计分析路由,对应 04 PRD 第十章 / 06 页面原型设计 页面八。

数据口径与案件总览同源:全部从内网同步快照(internal_case_trackings)聚合,
紧急度用 internal_case_urgency.compute_urgency 实时计算。累计收件/立案两个
历史总数优先取内网实时接口,不可用时退化为快照环节在办数;快照为空时返回
空结构(source=local),前端各图表显示空态。
"""

import logging
from collections import Counter
from datetime import date, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.v1.dashboard import (
    _as_local_date,
    _case_duration_days,
    _duration_bucket,
    _filed_date,
    _is_over_statutory_limit,
    _last_12_months,
    _LOCAL_TZ,
    _snapshot_rows,
    _DURATION_BUCKETS,
)
from app.core.config import get_settings
from app.db.session import get_db
from app.integrations.case_system import CaseSystemError, CaseSystemStatsService
from app.models.internal_case import InternalStage
from app.schemas.stats import (
    PersonStat,
    StatsKpis,
    StatsOverview,
    YearCompare,
    YearlyStatsOut,
    YearStats,
)
from app.schemas.dashboard import MonthlyTrendPoint, NameCount
from app.services.internal_case_urgency import ARCHIVED_STEP, CLOSED_STEP
from app.services.time_limits import effective_settings

router = APIRouter(prefix="/stats", tags=["stats"])

logger = logging.getLogger(__name__)


async def _live_totals() -> tuple[int, int] | None:
    """内网实时接口的累计收件/立案总数;不可用返回 None。"""
    if not get_settings().case_system_enabled:
        return None
    try:
        data = await CaseSystemStatsService().fetch_dashboard_summary()
        return data.get("pending_filing", 0), data.get("filed_awaiting_hearing", 0)
    except CaseSystemError as exc:
        logger.warning("内网累计总数不可用,统计页退化用快照数: %s", exc)
        return None


# 一裁终局口径:end_way_detail 里"部分终局/一裁终局"都算终局(工作人员 2026-08-25 确认)。
_FINAL_RULING_DETAILS = {"部分终局", "一裁终局"}
# 统计年度边界:12月10日~次年12月10日为一个统计年度,标签用结束年。
_STAT_MONTH = 12
_STAT_DAY = 10


def _stat_year(d: date) -> int:
    """统计年度标签(结束年):2026年度 = 2025-12-10 ~ 2026-12-10。"""
    return d.year + 1 if (d.month, d.day) >= (_STAT_MONTH, _STAT_DAY) else d.year


def _is_final_ruling(detail) -> bool:
    return isinstance(detail, str) and detail in _FINAL_RULING_DETAILS


def _aggregate(rows, year_fn, with_monthly: bool) -> dict[int, dict]:
    """按 year_fn(本地日期) 聚合立案/结案/调解/撤回/裁决/终局/审理时长。

    调撤率分子 = 调解(end_way="调解") + 撤回(end_way="撤回");
    一裁终局率分子 = end_way_detail ∈ {部分终局, 一裁终局},分母 = end_way="裁决"。
    """
    buckets: dict[int, dict] = {}

    def bucket(y: int) -> dict:
        b = buckets.setdefault(
            y,
            {
                "filed": 0,
                "closed": 0,
                "mediated": 0,
                "withdrawn": 0,
                "ruled": 0,
                "final": 0,
                "with_end_way": 0,
                "durations": [],
            },
        )
        if with_monthly:
            b.setdefault("monthly_filed", [0] * 12)
            b.setdefault("monthly_closed", [0] * 12)
        return b

    for row, _result in rows:
        if row.stage != InternalStage.HANDLE:
            continue
        payload = row.raw_payload or {}
        filed = _filed_date(row)
        if filed is not None:
            b = bucket(year_fn(filed))
            b["filed"] += 1
            if with_monthly:
                b["monthly_filed"][filed.month - 1] += 1
        if row.current_step in (CLOSED_STEP, ARCHIVED_STEP) and row.end_at is not None:
            end = _as_local_date(row.end_at)
            b = bucket(year_fn(end))
            b["closed"] += 1
            if with_monthly:
                b["monthly_closed"][end.month - 1] += 1
            if row.end_way:
                b["with_end_way"] += 1
                if row.end_way == "调解":
                    b["mediated"] += 1
                elif row.end_way == "撤回":
                    b["withdrawn"] += 1
                elif row.end_way == "裁决":
                    b["ruled"] += 1
                    if _is_final_ruling(payload.get("end_way_detail")):
                        b["final"] += 1
            duration = _case_duration_days(row)
            if duration is not None:
                b["durations"].append(duration)
    return buckets


def _aggregate_years(rows) -> tuple[dict[int, dict], list[int]]:
    """按自然年聚合(立案 handle_at 年、结案 end_at 年 + 逐月数据)。

    返回 (年份 -> 聚合 dict, 有数据的年份升序列表)。数据来自内网全量历史快照。
    """
    years = _aggregate(rows, lambda d: d.year, with_monthly=True)
    return years, sorted(years)


def _aggregate_stat_years(rows) -> tuple[dict[int, dict], list[int]]:
    """按统计年度(12-10~次年12-10)聚合,无逐月数据(仅 KPI 行)。"""
    years = _aggregate(rows, _stat_year, with_monthly=False)
    return years, sorted(years)


def _to_year_stats(year: int, agg: dict | None) -> YearStats:
    agg = agg or {}
    durations = agg.get("durations") or []
    with_end_way = agg.get("with_end_way", 0)
    ruled = agg.get("ruled", 0)
    filed = agg.get("filed", 0)
    closed = agg.get("closed", 0)
    mediated = agg.get("mediated", 0)
    withdrawn = agg.get("withdrawn", 0)
    final = agg.get("final", 0)
    return YearStats(
        year=year,
        filed=filed,
        closed=closed,
        mediated=mediated,
        withdrawn=withdrawn,
        final=final,
        closing_rate=round(closed / filed, 4) if filed else 0,
        mediation_rate=round(mediated / with_end_way, 4) if with_end_way else 0,
        mediation_withdrawal_rate=round((mediated + withdrawn) / with_end_way, 4) if with_end_way else 0,
        final_ruling_rate=round(final / ruled, 4) if ruled else 0,
        avg_duration_days=round(sum(durations) / len(durations), 1) if durations else 0,
    )


@router.get("/overview", response_model=StatsOverview)
async def get_stats_overview(
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user),
) -> StatsOverview:
    rows = await _snapshot_rows(db, await effective_settings(db))
    live = await _live_totals()
    if rows is None:
        # 快照为空(尚未同步过内网数据):没有可统计的真实数据,返回空结构。
        kpis = StatsKpis()
        if live is not None:
            kpis.receive_total, kpis.filed_total = live
        return StatsOverview(source="internal" if live is not None else "local", kpis=kpis)

    today = datetime.now(_LOCAL_TZ).date()
    months = _last_12_months(today)
    filed_by_month: Counter[str] = Counter()
    closed_by_month: Counter[str] = Counter()
    end_ways: Counter[str] = Counter()
    duration_buckets: Counter[str] = Counter()
    arbitrators: dict[str, PersonStat] = {}

    open_cases = 0
    closed_cases = 0
    overdue_cases = 0
    over_limit_open = 0
    over_limit_closed = 0
    receive_stage = 0
    durations: list[int] = []

    for row, result in rows:
        if result.urgency == "overdue":
            overdue_cases += 1
        if row.stage == InternalStage.RECEIVE:
            receive_stage += 1
            continue
        if row.stage != InternalStage.HANDLE:
            continue

        payload = row.raw_payload or {}
        is_closed = row.current_step in (CLOSED_STEP, ARCHIVED_STEP)
        if is_closed:
            closed_cases += 1
            if _is_over_statutory_limit(row, today):
                over_limit_closed += 1
        else:
            open_cases += 1
            if _is_over_statutory_limit(row, today):
                over_limit_open += 1

        # 仲裁员办案量
        name = payload.get("arbitrator") or "未分配"
        person = arbitrators.setdefault(name, PersonStat(name=name, total=0, open=0, closed=0))
        person.total += 1
        if is_closed:
            person.closed += 1
        else:
            person.open += 1

        handle_at = payload.get("handle_at")
        if isinstance(handle_at, str) and handle_at[:7] in months:
            filed_by_month[handle_at[:7]] += 1

        if is_closed:
            if row.end_at is not None:
                month = _as_local_date(row.end_at).strftime("%Y-%m")
                if month in months:
                    closed_by_month[month] += 1
            if row.end_way:
                end_ways[row.end_way] += 1
            duration = _case_duration_days(row)
            if duration is not None:
                durations.append(duration)
                duration_buckets[_duration_bucket(duration)] += 1

    mediated = end_ways.get("调解", 0)
    withdrawn = end_ways.get("撤回", 0)
    with_end_way = sum(end_ways.values())
    kpis = StatsKpis(
        receive_total=live[0] if live else receive_stage,
        filed_total=live[1] if live else closed_cases + open_cases,
        open_cases=open_cases,
        closed_cases=closed_cases,
        mediation_rate=round(mediated / with_end_way, 4) if with_end_way else 0,
        mediation_withdrawal_rate=round((mediated + withdrawn) / with_end_way, 4) if with_end_way else 0,
        avg_duration_days=round(sum(durations) / len(durations), 1) if durations else 0,
        overdue_cases=overdue_cases,
        over_limit_open=over_limit_open,
        over_limit_closed=over_limit_closed,
    )

    years, _available = _aggregate_years(rows)
    year_compare = YearCompare(
        this_year=_to_year_stats(today.year, years.get(today.year)),
        last_year=_to_year_stats(today.year - 1, years.get(today.year - 1)),
        monthly_filed_this=(years.get(today.year) or {}).get("monthly_filed", [0] * 12),
        monthly_filed_last=(years.get(today.year - 1) or {}).get("monthly_filed", [0] * 12),
        monthly_closed_this=(years.get(today.year) or {}).get("monthly_closed", [0] * 12),
        monthly_closed_last=(years.get(today.year - 1) or {}).get("monthly_closed", [0] * 12),
    )

    return StatsOverview(
        source="internal",
        kpis=kpis,
        monthly_trend=[
            MonthlyTrendPoint(
                month=m,
                filed=filed_by_month.get(m, 0),
                closed=closed_by_month.get(m, 0),
            )
            for m in months
        ],
        end_ways=[NameCount(name=k, count=v) for k, v in end_ways.most_common()],
        duration_buckets=[
            NameCount(name=b, count=duration_buckets.get(b, 0)) for b in _DURATION_BUCKETS
        ],
        arbitrator_stats=sorted(arbitrators.values(), key=lambda p: p.total, reverse=True),
        year_compare=year_compare,
    )


@router.get("/yearly", response_model=YearlyStatsOut)
async def get_yearly_stats(
    year: int,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user),
) -> YearlyStatsOut:
    """单一年份的案件统计(年度数据区):该年立案/结案/调解率/调撤率/一裁终局率/审理时长。

    同时返回同标签的统计年度(12-10~次年12-10)汇总,前端并列展示两行。
    """
    rows = await _snapshot_rows(db, await effective_settings(db))
    if rows is None:
        return YearlyStatsOut(year=year, monthly_filed=[0] * 12, monthly_closed=[0] * 12)

    years, available = _aggregate_years(rows)
    agg = years.get(year) or {}
    base = _to_year_stats(year, agg)

    stat_years, stat_available = _aggregate_stat_years(rows)
    stat_year = _to_year_stats(year, stat_years.get(year) or {})

    return YearlyStatsOut(
        year=year,
        filed=base.filed,
        closed=base.closed,
        mediated=base.mediated,
        withdrawn=base.withdrawn,
        final=base.final,
        closing_rate=base.closing_rate,
        mediation_rate=base.mediation_rate,
        mediation_withdrawal_rate=base.mediation_withdrawal_rate,
        final_ruling_rate=base.final_ruling_rate,
        avg_duration_days=base.avg_duration_days,
        monthly_filed=agg.get("monthly_filed", [0] * 12),
        monthly_closed=agg.get("monthly_closed", [0] * 12),
        available_years=sorted(set(available) | set(stat_available)),
        stat_year=stat_year,
    )
