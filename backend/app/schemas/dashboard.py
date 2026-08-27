from datetime import date, datetime

from pydantic import BaseModel


class DashboardSummary(BaseModel):
    """案件总览（原 PRD 称"首页驾驶舱"），对应 04 PRD 模块一 / 06 页面原型设计 页面一。"""

    due_reminders: int = 0  # 时效提醒:已超期/紧急/临近的案件数
    hearings_upcoming: int = 0  # 近日开庭:今日 ~ 下周日的开庭场次
    pending_mediation: int = 0
    pending_receive: int = 0  # 待办案件:收件环节待审核、尚未立案的案件数
    pre_mediation: int = 0  # 案前调解:收件环节 next_step=3(收件审核通过后进入调解)的案件数
    pre_mediation_soon: int = 0  # 其中进入调解满 30 天(临近)的案件数
    pre_mediation_urgent: int = 0  # 其中进入调解满 45 天(紧急)的案件数
    open_cases: int = 0  # 在办案件:已立案未结案(含中止/调解/裁决中)的案件数
    heard_awaiting_decision: int = 0
    paused_long: int = 0  # 中止过久:审理中止超过阈值的案件数
    today_filed: int = 0  # 今日立案:内网 handle_at 为今日的案件数
    today_closed: int = 0  # 今日结案:已结案/已归档且 end_at 为今日的案件数
    note_cases: int = 0  # 记事本:近 tag_overview_days 天内有记事的案件数

    # 数据来源:"internal" = 内网案件系统,"local" = 本地 Case 表回退。
    source: str = "local"


class HearingOut(BaseModel):
    """一场开庭安排(来自内网 getAllHoldCourt)。"""

    case_no: str
    case_id: str | None = None
    open_at: datetime
    end_at: datetime | None = None
    tribunal_name: str | None = None
    arbitrator: str | None = None
    clerk: str | None = None
    current_step: str | None = None
    applicant: str | None = None
    respondent: str | None = None


class HearingListOut(BaseModel):
    start: date
    end: date
    total: int
    items: list[HearingOut]


class MonthlyTrendPoint(BaseModel):
    """某自然月的立案/结案数(来自内网 handle_at / end_at)。"""

    month: str  # YYYY-MM
    filed: int
    closed: int


class NameCount(BaseModel):
    name: str
    count: int


class DashboardCharts(BaseModel):
    """总览图表数据,全部从内网同步快照聚合(口径与卡片一致,见 dashboard.py)。"""

    monthly_trend: list[MonthlyTrendPoint]  # 近 12 个月立案/结案趋势
    open_steps: list[NameCount]  # 在办案件状态分布(handle 环节未结案/未归档)
    end_ways: list[NameCount]  # 结案方式分布(调解/裁决/撤回/撤销)
    urgency: list[NameCount]  # 在办案件紧急度分布(不含已结案/已退回)
