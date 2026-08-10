from pydantic import BaseModel

from app.schemas.dashboard import MonthlyTrendPoint, NameCount


class StatsKpis(BaseModel):
    """统计分析页顶部 KPI 卡,全部来自内网真实数据。"""

    receive_total: int = 0  # 累计收件(内网实时 totalNum,历史累计)
    filed_total: int = 0  # 累计立案(同上)
    open_cases: int = 0  # 在办案件(handle 未结案/未归档)
    closed_cases: int = 0  # 已结案(含已归档)
    mediation_rate: float = 0  # 调解率 = 调解结案 / 有结案方式的已结案件
    avg_duration_days: float = 0  # 平均审理天数(结案日 - 立案日 - 中止天数)
    overdue_cases: int = 0  # 当前超期案件数(紧急度 overdue)
    over_limit_open: int = 0  # 在办超审限(经过天数扣中止 > 45天+延期)
    over_limit_closed: int = 0  # 结案时超审限的案件数(回顾性)


class PersonStat(BaseModel):
    """仲裁员/书记员办案量。"""

    name: str
    total: int  # 经办总案数
    open: int  # 其中在办
    closed: int  # 其中已结案/已归档


class YearStats(BaseModel):
    """单个自然年的汇总。"""

    year: int
    filed: int = 0  # 立案数(handle_at 落在该年)
    closed: int = 0  # 结案数(end_at 落在该年)
    mediation_rate: float = 0  # 该年调解率(调解结案/有结案方式的结案)
    avg_duration_days: float = 0  # 该年结案案件的平均审理天数(扣中止)


class YearCompare(BaseModel):
    """今年 vs 去年对比;monthly_* 为 1~12 月的逐月数据,供分组柱状图。"""

    this_year: YearStats
    last_year: YearStats
    monthly_filed_this: list[int] = []
    monthly_filed_last: list[int] = []
    monthly_closed_this: list[int] = []
    monthly_closed_last: list[int] = []


class YearlyStatsOut(BaseModel):
    """单一年份的案件统计(年度数据区);monthly_* 为 1~12 月逐月数据。"""

    year: int
    filed: int = 0  # 该年立案数
    closed: int = 0  # 该年结案数
    mediation_rate: float = 0  # 该年调解率
    avg_duration_days: float = 0  # 该年结案平均审理天数(扣中止)
    monthly_filed: list[int] = []
    monthly_closed: list[int] = []
    available_years: list[int] = []  # 快照中出现过立案/结案的年份(供年份选择器)


class StatsOverview(BaseModel):
    """统计分析页聚合,对应 04 PRD 第十章;口径与案件总览同源(内网同步快照)。"""

    source: str = "local"  # internal = 内网真实数据,local = 本地模拟回退
    kpis: StatsKpis
    monthly_trend: list[MonthlyTrendPoint] = []  # 近 12 个月立案/结案趋势
    end_ways: list[NameCount] = []  # 结案方式分布
    duration_buckets: list[NameCount] = []  # 审理时长分布(法定审限 45 天分桶)
    arbitrator_stats: list[PersonStat] = []  # 仲裁员办案量(按总量降序)
    year_compare: YearCompare | None = None  # 今年 vs 去年
