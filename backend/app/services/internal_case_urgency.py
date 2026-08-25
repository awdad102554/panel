"""内网案件紧急度计算(纯函数,读取时按当前日期实时计算,不落库)。

优先级:人工时效覆盖 > 环节原生倒计时/超期信号 > 按进入当前环节的天数估算。
已确认口径(工作人员 2026-07-24 确认;2026-07-30 取消结案后的送达跟踪,结案即终态):
- 审理中止(is_paused)标"已中止XX天";暂停超过 case_urgency_paused_alert_days
  升级为 paused_overdue 单独提醒(days_remaining 存已中止天数,供前端显示)。
- 已结案 = 终态,直接按 closed 处理(默认隐藏),不再跟踪结案后的送达环节;
  已归档同为终态。
- 未通过/退回状态(结案审核未通过/结案审批未通过/处理文书审批未通过)意味着要
  返工,按最高优先级红色 overdue 提醒。
- 组织调解:进入调解环节超过 case_mediation_alert_days 天(约一个月)提醒(soon)。
- reserve.status 枚举:0 待审核 / 1 审核通过 / 2 审核不通过 / 3 现场确认同意 / 4 现场确认不同意。
- receive.status 枚举:0 收件登记 / 1 审核通过 / 2 审核不通过 / 3 审批通过 / 4 审批不通过 / 5 已提交。
  两者都是 0=工作人员待办(按原生倒计时/天数监控),其余=已离开待办(审核/审批通过已流转、
  不通过已退回),单列 rejected 默认隐藏(receive 的 next_step=3 案前调解除外,见下)。
  收件/预约超期按红色 overdue 提醒。
- current_step 枚举不封闭,未识别的子状态按普通 handle 在办处理,不报错。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from app.core.config import Settings
from app.models.internal_case import (
    CaseTimeLimitOverride,
    InternalCaseTracking,
    InternalStage,
)

# 业务本地时区(CST):天数以本地自然日为准,不用 UTC 日期。
_LOCAL_TZ = timezone(timedelta(hours=8))

CLOSED_STEP = "已结案"
ARCHIVED_STEP = "已归档"  # 已归档:比结案更终态,直接按 closed 隐藏。
PAUSED_STEP = "审理中止"
MEDIATION_STEP = "组织调解"
DECIDING_STEP = "仲裁裁决中"  # 已开庭、等待裁决(案件总览"已开庭待裁决"的口径)
# 未通过/退回状态:需要返工,红色 overdue 级提醒。
REWORK_STEPS = frozenset({"结案审核未通过", "结案审批未通过", "处理文书审批未通过"})

# 收件环节 next_step=3 = 案前调解(收件审核通过后进入调解),区别于 handle 阶段的
# "组织调解"。案前调解是活跃状态(调解中),不是"已处理/退回",单独一张总览卡片
# 跟踪其时效:进入调解满 soon 天标"临近"、满 urgent 天标"紧急/警告"(2026-08-24)。
PRE_MEDIATION_NEXT_STEP = 3
PRE_MEDIATION_STEP_LABEL = "案前调解"

# 紧急度枚举(与前端 InternalCaseUrgency 对应)。
UrgencyLevel = str  # "overdue"|"urgent"|"soon"|"normal"|"paused"|"paused_overdue"|"closed"|"rejected"

# 列表排序权重:数字越小越靠前。中止过久只是"停滞提醒"(2026-07-31 确认),
# 不属于高紧急度,排在正常之后;中止过久案件另有总览单独卡片展示。
_URGENCY_ORDER = {
    "overdue": 0,
    "urgent": 1,
    "soon": 2,
    "normal": 3,
    "paused_overdue": 4,
    "paused": 5,
    "closed": 6,
    "rejected": 7,
}


@dataclass
class UrgencyResult:
    urgency: UrgencyLevel
    days_remaining: int | None  # 负数=已超期;None=无倒计时口径
    source: str  # "override" | "native" | "elapsed" | "status"

    @property
    def order(self) -> int:
        return _URGENCY_ORDER.get(self.urgency, 99)


def urgency_order(level: str) -> int:
    """紧急度排序权重(供列表混排,数字越小越靠前)。"""
    return _URGENCY_ORDER.get(level, 99)


def sort_days_key(urgency: str, days_remaining: int | None) -> int:
    """同档内排序的天数键(与 urgency_order 配合使用)。

    普通档位 days_remaining 是剩余天数,越少越紧急(升序);中止档位的
    days_remaining 存的是"已中止天数"(正数),停滞越久越该靠前(取负)。
    """
    days = days_remaining or 0
    return -days if urgency in ("paused", "paused_overdue") else days


def _by_days(days_remaining: int, soon_days: int, urgent_days: int = 1) -> UrgencyLevel:
    """按剩余天数分档:超期 < 紧急(≤urgent_days) < 临近(≤soon_days) < 正常。"""
    if days_remaining < 0:
        return "overdue"
    if days_remaining <= urgent_days:
        return "urgent"
    if days_remaining <= soon_days:
        return "soon"
    return "normal"


def compute_urgency(
    row: InternalCaseTracking,
    override: CaseTimeLimitOverride | None,
    settings: Settings,
    today: date | None = None,
) -> UrgencyResult:
    # 默认"今天"用业务本地日期(CST),与 _as_date 的口径一致;服务器系统时区不是
    # CST 时,UTC/CST 日界前后(0:00-8:00)不至于把天数算偏 1 天。
    today = today or datetime.now(_LOCAL_TZ).date()

    # 0. 已结案/已归档是终态,优先于一切(含人工覆盖)——"结案即终态"口径:
    # 已结案案件设过人工覆盖也不应重新出现在时效提醒里(2026-08-10 修正,
    # 此前 override 优先,终态案件会因覆盖重新告警)。
    if row.stage == InternalStage.HANDLE and row.current_step in (CLOSED_STEP, ARCHIVED_STEP):
        return UrgencyResult("closed", None, "status")

    # 1. 人工时效覆盖优先。
    if override is not None:
        days = (override.deadline_override - today).days
        return UrgencyResult(_by_days(days, settings.case_urgency_soon_days, settings.case_urgency_urgent_days), days, "override")

    # stage 列显式声明为 String,从库中读回是 str 而非枚举,故用 == 而非 is 比较。
    if row.stage == InternalStage.HANDLE:
        # 2a. 未通过/退回状态:需要返工,红色 overdue 级最高优先。
        if row.current_step in REWORK_STEPS:
            return UrgencyResult("overdue", None, "status")
        # 2b. 审理中止:标"已中止XX天";暂停超过阈值升级为 paused_overdue 提醒。
        # days_remaining 存"已中止天数"(正数),供前端显示"中止XX天"。
        if row.is_paused or row.current_step == PAUSED_STEP:
            paused_days = (today - _as_date(row.phase_entered_at)).days
            if paused_days > settings.case_urgency_paused_alert_days:
                return UrgencyResult("paused_overdue", paused_days, "elapsed")
            return UrgencyResult("paused", paused_days, "elapsed")
        # 2c. 组织调解:无原生时限,进入调解环节超过约一个月提醒。
        # days_remaining 传 None:调解没有"剩余天数"概念,传负数前端会误显"已超期 X 天"。
        if row.current_step == MEDIATION_STEP:
            mediation_days = (today - _as_date(row.phase_entered_at)).days
            if mediation_days > settings.case_mediation_alert_days:
                return UrgencyResult("soon", None, "elapsed")
            return UrgencyResult("normal", settings.case_mediation_alert_days - mediation_days, "elapsed")
        # 2d. 普通在办:用原生剩余审理天数。
        if row.native_remaining_days is not None:
            return UrgencyResult(
                _by_days(row.native_remaining_days, settings.case_urgency_soon_days, settings.case_urgency_urgent_days),
                row.native_remaining_days,
                "native",
            )
        # 没有 closing_time_limit 的在办案件,按进入环节天数兜底(估算时限=临近阈值)。
        return _elapsed_urgency(
            row, today, settings.case_urgency_soon_days,
            settings.case_urgency_soon_days, settings.case_urgency_urgent_days,
        )

    if row.stage == InternalStage.RESERVE:
        # reserve.status 枚举(用户确认的权威口径):0 待审核 / 1 审核通过 /
        # 2 审核不通过 / 3 现场确认通过 / 4 现场确认不通过。
        # 不通过(2/4)是退回申请人补正,不是工作人员待办,单列 rejected 不算超期;
        # 通过(1/3)表示 reserve 环节工作人员的动作已完成,不告警;
        # 待审核(0)才是工作人员该推进的:优先用内网原生 reserve_time_limit 倒计时
        # (解析成的 native_remaining_days,与收件同一套临近/紧急阈值,超期红色 overdue),
        # 拿不到再按进入天数估算。
        reserve_status = (row.raw_payload or {}).get("status")
        if reserve_status in (2, 4):
            return UrgencyResult("rejected", None, "status")
        if reserve_status in (1, 3):
            return UrgencyResult("normal", None, "status")
        if row.native_remaining_days is not None:
            return UrgencyResult(
                _by_days(row.native_remaining_days, settings.case_urgency_soon_days, settings.case_urgency_urgent_days),
                row.native_remaining_days,
                "native",
            )
        return _elapsed_urgency(
            row, today, settings.case_urgency_reserve_days,
            settings.case_urgency_soon_days, settings.case_urgency_urgent_days,
        )

    # 4. 收件:receive.status 枚举 0 收件登记(待办)/1 审核通过/2 审核不通过/
    # 3 审批通过/4 审批不通过/5 已提交——只有 0 是工作人员待办,其余都已离开待办
    # (审核/审批通过已流转、不通过已退回),单列 rejected 默认隐藏,不再按 receive_at
    # 计算天数(否则早年审结的老收件会永远挂在列表里报"临近")。
    # 但案前调解(next_step=3)是例外:虽 status=3(审批通过),仍是活跃的调解状态,
    # 不是"已离开/退回",不能单列 rejected——单独按进入调解 30/45 天分档(2026-08-24)。
    if is_pre_mediation(row):
        return compute_pre_mediation_urgency(row.raw_payload or {}, settings, today)
    receive_status = (row.raw_payload or {}).get("status")
    if receive_status is not None and receive_status != 0:
        return UrgencyResult("rejected", None, "status")
    # 待审核:用内网原生 receive_time_limit(解析成的 native_remaining_days),
    # 警告分档与在办案件同一套阈值(临近/紧急),超时限红色 overdue 提醒。
    if row.native_remaining_days is not None:
        return UrgencyResult(
            _by_days(row.native_remaining_days, settings.case_urgency_soon_days, settings.case_urgency_urgent_days),
            row.native_remaining_days,
            "native",
        )
    return _elapsed_urgency(
        row, today, settings.case_urgency_receive_days,
        settings.case_urgency_soon_days, settings.case_urgency_urgent_days,
    )


def _elapsed_urgency(
    row: InternalCaseTracking,
    today: date,
    limit_days: int,
    soon_days: int,
    urgent_days: int = 1,
) -> UrgencyResult:
    """按"进入当前环节已过天数 vs 环节时限"估算紧急度。

    剩余 = 环节时限(limit_days) - 已过天数;警告分档统一用临近/紧急阈值:
    剩余<0 超期、≤紧急阈值 紧急、≤临近阈值 临近、否则正常。
    环节的法定时限(收件 5 天、预约 3 天)只决定超期点,不决定警告起点——
    否则新案件一进来剩 5 天就会被误标"临近"(2026-08-06 修正的口径错位)。
    """
    elapsed = (today - _as_date(row.phase_entered_at)).days
    remaining = limit_days - elapsed
    return UrgencyResult(_by_days(remaining, soon_days, urgent_days), remaining, "elapsed")


def _as_date(value: datetime) -> date:
    """取业务本地日期(CST)。

    快照里的时间戳是带时区的 UTC,直接 .date() 会得到 UTC 日期,
    在 UTC 日界前后与本地日期相差一天,使天数计算偏 1 天。
    """
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(_LOCAL_TZ).date()
        return value.date()
    return value


def _coerce_int(value) -> int | None:
    """宽容转 int:JSONB 里可能是 int,内网也可能回字符串 "3",统一转 int 比较。"""
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None


def is_pre_mediation(row: InternalCaseTracking) -> bool:
    """收件环节 next_step=3 即案前调解(仍在调解中,活跃状态,不是已离开/已退回)。"""
    if row.stage != InternalStage.RECEIVE:
        return False
    return _coerce_int((row.raw_payload or {}).get("next_step")) == PRE_MEDIATION_NEXT_STEP


def _pre_mediation_entry_datetime(payload: dict) -> datetime | None:
    """进入案前调解的时间锚点(带时分秒):review_at(收件审核通过、转入调解),
    缺省回落 receive_at/created_at。

    内网时间戳是无时区的本地时间(CST),strptime 后即本地时间,无需再换算时区。
    """
    for key in ("review_at", "receive_at", "created_at"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
    return None


def pre_mediation_entered_at(payload: dict) -> datetime | None:
    """案前调解的进入时间(公开:明细列表"进入状态时间"列用,仅对案前调解案件有意义)。"""
    return _pre_mediation_entry_datetime(payload)


def _pre_mediation_entry_date(payload: dict) -> date | None:
    """进入案前调解的日期(用于 30/45 天分档)。"""
    dt = _pre_mediation_entry_datetime(payload)
    return dt.date() if dt is not None else None


def compute_pre_mediation_urgency(
    payload: dict,
    settings: Settings,
    today: date,
) -> UrgencyResult:
    """案前调解案件紧急度:进入调解满 soon 天标"临近"、满 urgent 天标"紧急/警告"
    (用户口径 30/45 天)。

    days_remaining = urgent 阈值 − 已过天数;负值表示已过"警告"点,前端显示"已超期 X 天"。
    与 virtual_case 的两阈值分档同构(临近阈值在前、紧急阈值在后)。
    """
    entry = _pre_mediation_entry_date(payload)
    if entry is None:
        return UrgencyResult("normal", None, "status")
    elapsed = (today - entry).days
    remaining = settings.pre_mediation_urgent_days - elapsed
    if elapsed >= settings.pre_mediation_urgent_days:
        return UrgencyResult("urgent", remaining, "elapsed")
    if elapsed >= settings.pre_mediation_soon_days:
        return UrgencyResult("soon", remaining, "elapsed")
    return UrgencyResult("normal", remaining, "elapsed")
