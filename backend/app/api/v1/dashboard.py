from datetime import date, datetime, timedelta, timezone
from collections import Counter
import logging

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.v1.internal_cases import _build_out, _load_overrides
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.integrations.case_system import CaseSystemError
from app.models.case import Case, CaseStatus
from app.models.internal_case import (
    CaseTimeLimitOverride,
    InternalCaseTracking,
    InternalStage,
)
from app.schemas.dashboard import (
    DashboardCharts,
    DashboardSummary,
    HearingListOut,
    HearingOut,
    MonthlyTrendPoint,
    NameCount,
)
from app.schemas.internal_case import InternalCaseOut
from app.services.internal_case_urgency import (
    ARCHIVED_STEP,
    CLOSED_STEP,
    DECIDING_STEP,
    MEDIATION_STEP,
    UrgencyResult,
    compute_pre_mediation_urgency,
    compute_urgency,
    is_pre_mediation,
    sort_days_key,
    urgency_order,
)
from app.services.internal_hearing import fetch_hearings, upcoming_range
from app.services.pre_mediation_binding import load_bound_receive_ids
from app.services.time_limits import effective_settings, get_time_limits
from app.api.v1.virtual_cases import list_pending_virtual_cases
from app.db.virtual import VirtualCase

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

logger = logging.getLogger(__name__)

# 业务本地时区(CST):"今日"类统计以本地自然日为准,不用 UTC 日期。
_LOCAL_TZ = timezone(timedelta(hours=8))


async def _count(db: AsyncSession, *where) -> int:
    stmt = select(func.count()).select_from(Case)
    for clause in where:
        stmt = stmt.where(clause)
    result = await db.execute(stmt)
    return result.scalar_one()


async def _local_summary(db: AsyncSession) -> DashboardSummary:
    # 与快照路径统一用业务本地日期(CST),不用系统时区。
    today = datetime.now(_LOCAL_TZ).date()
    soon = today + timedelta(days=7)

    return DashboardSummary(
        due_reminders=await _count(
            db, Case.statute_deadline.is_not(None), Case.statute_deadline <= soon
        ),
        pending_mediation=await _count(db, Case.status == CaseStatus.MEDIATION),
        pending_receive=await _count(db, Case.status == CaseStatus.PRE_REVIEW),
        open_cases=await _count(db, Case.status.in_([CaseStatus.FILED, CaseStatus.PRE_HEARING])),
        heard_awaiting_decision=await _count(
            db, Case.status.in_([CaseStatus.HEARING, CaseStatus.POST_HEARING])
        ),
        source="local",
    )


async def _upcoming_hearing_count() -> int:
    """近日开庭场次;内网不可用时按 0 计,不让总览整页失败。"""
    try:
        start, end = upcoming_range()
        return len(await fetch_hearings(start, end))
    except CaseSystemError as exc:
        logger.warning("近日开庭数量获取失败: %s", exc)
        return 0


def _as_local_date(value: datetime) -> date:
    """带时区时间戳转业务本地(CST)日期,与 internal_case_urgency 的口径一致。"""
    if value.tzinfo is not None:
        return value.astimezone(_LOCAL_TZ).date()
    return value.date()


def _case_duration_days(row: InternalCaseTracking) -> int | None:
    """审理时长(天) = 结案日期 - 立案日期 - 中止天数,按本地日期算;同一天结案件计 0 天。

    中止天数来自 internal_case_pause 的回填(review_matter 中止/恢复审理配对);
    未回填(paused_days 为 None)按 0 计,即暂时退化为不扣中止的自然日时长。
    数据不全(非结案/缺 end_at/handle_at)时返回 None。
    """
    if row.current_step not in (CLOSED_STEP, ARCHIVED_STEP) or row.end_at is None:
        return None
    filed = _filed_date(row)
    if filed is None:
        return None
    calendar_days = (_as_local_date(row.end_at) - filed).days
    return max(0, calendar_days - (row.paused_days or 0))


# 法定审限(劳动仲裁 45 天);批准的延期天数加在内网 payload.extension_days 上。
_STATUTORY_LIMIT_DAYS = 45


def _filed_date(row: InternalCaseTracking) -> date | None:
    """立案日期(handle_at,本地日期);取不到返回 None。"""
    handle_at = (row.raw_payload or {}).get("handle_at")
    if not isinstance(handle_at, str) or len(handle_at) < 10:
        return None
    try:
        return datetime.strptime(handle_at[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _statutory_limit_days(row: InternalCaseTracking, base: int = _STATUTORY_LIMIT_DAYS) -> int:
    """该案的审限 = 法定审限(固定 45 天,业务规则定值不开放设置) + 已批准延期
    (内网 extension_days,与 review_matter "延长审理期限"记录一致)。"""
    raw = (row.raw_payload or {}).get("extension_days")
    try:
        extension = int(float(str(raw or 0).strip()))
    except (TypeError, ValueError):
        extension = 0
    return base + max(0, extension)


def _is_over_statutory_limit(
    row: InternalCaseTracking, today: date, statutory_limit_days: int = _STATUTORY_LIMIT_DAYS
) -> bool:
    """是否超审限:实际经过天数(扣除中止期间) > 法定审限 + 批准延期。

    起算日:立案日;若发生审限重新计算(变更/增加仲裁请求、反申请、追加当事人
    被受理),从最近一次重启日起算,且只扣重启日之后的中止(paused_after_reset_days);
    无重启则扣全量中止(paused_days)。结案案件算到结案日,在办案件算到今天。
    statutory_limit_days 默认 45(法定审限,固定规则值;参数仅供测试注入)。
    """
    if row.clock_reset_at is not None:
        start = row.clock_reset_at
        paused = row.paused_after_reset_days or 0
    else:
        start = _filed_date(row)
        paused = row.paused_days or 0
    if start is None:
        return False
    if row.current_step in (CLOSED_STEP, ARCHIVED_STEP):
        if row.end_at is None:
            return False
        end = _as_local_date(row.end_at)
    else:
        end = today
    elapsed = (end - start).days - paused
    return elapsed > _statutory_limit_days(row, statutory_limit_days)


# 审理时长分桶:45 天是劳动仲裁法定审限,可延长 15 天(60 天),再往上单列。
_DURATION_BUCKETS = ("≤45天", "46-60天", "61-90天", ">90天")


def _duration_bucket(days: int) -> str:
    if days <= 45:
        return "≤45天"
    if days <= 60:
        return "46-60天"
    if days <= 90:
        return "61-90天"
    return ">90天"


# 一裁终局口径:end_way_detail 里"部分终局/一裁终局"都算终局(工作人员 2026-08-25 确认)。
_FINAL_RULING_DETAILS = {"部分终局", "一裁终局"}
# 统计年度边界:上一年12月11日~当年12月10日为一个统计年度(12月10日为年末截止日,
# 含当天),标签用结束年。
_STAT_MONTH = 12
_STAT_DAY = 10


def _stat_year(d: date) -> int:
    """统计年度标签(结束年):2026年度 = 2025-12-11 ~ 2026-12-10(含 12月10日当天)。"""
    return d.year + 1 if (d.month, d.day) > (_STAT_MONTH, _STAT_DAY) else d.year


def _is_final_ruling(detail) -> bool:
    return isinstance(detail, str) and detail in _FINAL_RULING_DETAILS


async def _snapshot_rows(
    db: AsyncSession,
    settings: Settings | None = None,
) -> list[tuple[InternalCaseTracking, UrgencyResult]] | None:
    """加载内网同步快照全部案件并逐个算出紧急度(与办案进度监控页同一套逻辑)。

    settings 可传"时限设置"生效后的副本(见 services/time_limits.effective_settings),
    不传则用 config 默认值。返回 (快照行, 紧急度) 列表;快照为空返回 None。
    """
    rows = (await db.execute(select(InternalCaseTracking))).scalars().all()
    if not rows:
        return None

    settings = settings or get_settings()
    overrides = {
        o.external_case_id: o
        for o in (await db.execute(select(CaseTimeLimitOverride))).scalars()
    }
    return [
        (
            row,
            compute_urgency(
                row,
                overrides.get(row.external_case_id),
                settings,
            ),
        )
        for row in rows
    ]


# 可从快照聚合/列明细的卡片 key(前端卡片 key 与此一一对应)。
_SNAPSHOT_CARD_KEYS = (
    "due_reminders",
    "pending_mediation",
    "pending_receive",
    "pre_mediation",
    "open_cases",
    "heard_awaiting_decision",
    "paused_long",
    "today_filed",
    "today_closed",
)

def _virtual_case_out(row: VirtualCase, settings: Settings, today: date) -> InternalCaseOut:
    """预登记案件 → 卡片明细条目。紧急度按登记后的自然日数分档(阈值见时限设置
    virtual_case_soon_days / virtual_case_urgent_days,默认 30/60 天):超过临近阈值
    标"临近",超过紧急阈值标"紧急";days_remaining 存距紧急阈值的天数。环节标记为 virtual(预登记)。"""
    created_at = row.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    elapsed = (today - created_at.astimezone(_LOCAL_TZ).date()).days
    if elapsed >= settings.virtual_case_urgent_days:
        urgency = "urgent"
    elif elapsed >= settings.virtual_case_soon_days:
        urgency = "soon"
    else:
        urgency = "normal"
    remaining = settings.virtual_case_urgent_days - elapsed
    applicants = row.applicants or []
    respondents = row.respondents or []
    return InternalCaseOut(
        external_case_id=row.id,
        stage=InternalStage.VIRTUAL,
        current_step="待录入内网",
        case_no=row.receipt_number,
        applicant="、".join(p.get("name", "") for p in applicants if isinstance(p, dict) and p.get("name")) or None,
        respondent="、".join(p.get("name", "") for p in respondents if isinstance(p, dict) and p.get("name")) or None,
        is_paused=False,
        native_remaining_days=None,
        extension_days=0,
        end_at=None,
        end_way=None,
        phase_entered_at=created_at,
        last_synced_at=row.updated_at,
        urgency=urgency,
        days_remaining=remaining,
        urgency_source="elapsed",
        has_override=False,
        override_deadline=None,
    )


# 计数与明细共用的卡片口径,改动只动这里,卡片数字和点开后的列表永远对得上。
def _row_in_card(
    key: str,
    row: InternalCaseTracking,
    urgency: str,
    today: date,
    bound_receive_ids: frozenset[str] = frozenset(),
) -> bool:
    if key == "due_reminders":
        # 时效提醒:已超期(含审批退回返工) + 紧急 + 临近。
        # 案前调解(next_step=3)的"临近/紧急"是调解时长警告(30/45天),非硬截止日,
        # 单列在"案前调解"卡片跟踪,不进时效提醒(否则会被算成"已超期",2026-08-24)。
        return urgency in ("overdue", "urgent", "soon") and not is_pre_mediation(row)
    if key == "paused_long":
        # 中止过久:审理中止超过 case_urgency_paused_alert_days 的案件。
        return urgency == "paused_overdue"
    if key == "pending_receive":
        # 待办案件(2026-08-17 确认口径):收件环节或线上预约待审核(status=0)、
        # 尚未立案的案件,即需要工作人员审查推进的事项。已处理/已退回的不算。
        return (
            row.stage in (InternalStage.RECEIVE, InternalStage.RESERVE)
            and (row.raw_payload or {}).get("status") == 0
        )
    if key == "open_cases":
        # 在办案件:已立案、未结案未归档(含中止/调解/裁决中等子状态)。
        return (
            row.stage == InternalStage.HANDLE
            and row.current_step not in (CLOSED_STEP, ARCHIVED_STEP)
        )
    if key == "pending_mediation":
        return row.stage == InternalStage.HANDLE and row.current_step == MEDIATION_STEP
    if key == "pre_mediation":
        # 案前调解:收件环节 next_step=3(收件审核通过后进入调解,活跃状态)。
        # 已绑定立案(进入下一阶段)的案前调解不再计入,见 pre_mediation_bindings。
        return is_pre_mediation(row) and row.external_case_id not in bound_receive_ids
    if key == "heard_awaiting_decision":
        return row.stage == InternalStage.HANDLE and row.current_step == DECIDING_STEP
    if key == "today_filed":
        handle_at = (row.raw_payload or {}).get("handle_at")
        return (
            row.stage == InternalStage.HANDLE
            and isinstance(handle_at, str)
            and handle_at[:10] == today.isoformat()
        )
    if key == "today_closed":
        # 已结案/已归档都算结案(与月趋势图、统计页口径一致)。
        return (
            row.current_step in (CLOSED_STEP, ARCHIVED_STEP)
            and row.end_at is not None
            and _as_local_date(row.end_at) == today
        )
    return False


async def _snapshot_stats(db: AsyncSession) -> dict[str, int] | None:
    """从内网同步快照(internal_case_trackings)聚合总览卡片计数。

    口径(与办案进度监控页共用同一套 compute_urgency 紧急度逻辑,两页数字互相对得上):
    - due_reminders(时效提醒): 紧急度为 overdue / urgent / soon 的案件数,
      即时效维度需要处理的事项(已超期、审批退回返工、紧急、临近);案前调解
      单列在"案前调解"卡片,不计入时效提醒。
    - pending_receive(待办案件): 收件环节或线上预约待审核(status=0)、尚未立案
      的案件 + 待录入内网的预登记案件(SQLite,见 db/virtual.py)。
    - open_cases(在办案件): handle 环节未结案/未归档的案件。
    - pending_mediation(待调解): handle 环节 current_step=组织调解。
    - pre_mediation(案前调解): 收件环节 next_step=3(收件审核通过后进入调解);
      另返回 pre_mediation_soon/pre_mediation_urgent 分档计数(满 30/45 天)。
    - heard_awaiting_decision(已开庭待裁决): handle 环节 current_step=仲裁裁决中。
    - paused_long(中止过久): 审理中止超过 case_urgency_paused_alert_days 的案件。
    - today_filed(今日立案): handle 环节原生 handle_at 为今日(本地日期)。
    - today_closed(今日结案): 已结案/已归档且 end_at 为今日(本地日期)。

    快照为空(尚未同步过内网数据)时返回 None,由调用方回退本地统计。
    """
    rows = await _snapshot_rows(db, await effective_settings(db))
    if rows is None:
        return None

    # 已绑定立案的案前调解(进入下一阶段)不再计入案前调解卡片及其临近/紧急分档。
    bound_receive_ids = frozenset(await load_bound_receive_ids(db))

    today = datetime.now(_LOCAL_TZ).date()
    stats = {key: 0 for key in _SNAPSHOT_CARD_KEYS}
    stats["pre_mediation_soon"] = 0
    stats["pre_mediation_urgent"] = 0
    for row, result in rows:
        for key in _SNAPSHOT_CARD_KEYS:
            if _row_in_card(key, row, result.urgency, today, bound_receive_ids):
                stats[key] += 1
        # 案前调解「临近/紧急」分档计数(满 30/45 天),供总览卡片右上角提醒。
        if is_pre_mediation(row) and row.external_case_id not in bound_receive_ids:
            if result.urgency == "soon":
                stats["pre_mediation_soon"] += 1
            elif result.urgency == "urgent":
                stats["pre_mediation_urgent"] += 1
    # 待办案件并入待录入内网的预登记案件(本地 SQLite)。
    stats["pending_receive"] += len(await list_pending_virtual_cases())
    return stats


async def _note_cases_count(db: AsyncSession) -> int:
    """近 N 天(时限设置 tag_overview_days)有记事的案件数;MySQL 不可用按 0,不拖垮总览。"""
    from app.db.mysql import MysqlSessionLocal
    from app.services.case_tags import count_tagged_cases

    try:
        days = (await get_time_limits(db))["tag_overview_days"]
        async with MysqlSessionLocal() as mdb:
            return await count_tagged_cases(mdb, days)
    except Exception as exc:
        logger.warning("记事本总览计数获取失败: %s", exc)
        return 0


@router.get("/summary", response_model=DashboardSummary)
async def get_dashboard_summary(
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user),
) -> DashboardSummary:
    """案件总览统计,对应 04 PRD 模块一。

    卡片全部来自内网同步快照(internal_case_trackings,口径见 _snapshot_stats),
    开庭场次实时取内网庭审日历;快照为空时回退本地 Case 聚合(模拟数据)。
    记事本卡片计数来自 MySQL case_tags(近 tag_overview_days 天有记事的案件)。
    """

    snapshot = await _snapshot_stats(db)
    if snapshot is not None:
        return DashboardSummary(
            source="internal",
            hearings_upcoming=await _upcoming_hearing_count(),
            note_cases=await _note_cases_count(db),
            **snapshot,
        )

    local = await _local_summary(db)
    local.note_cases = await _note_cases_count(db)
    return local


@router.get("/hearings", response_model=HearingListOut)
async def list_upcoming_hearings(
    _current_user=Depends(get_current_user),
) -> HearingListOut:
    """近日开庭明细(今日 ~ 下周日),供总览卡片点开后展示。"""
    start, end = upcoming_range()
    try:
        hearings = await fetch_hearings(start, end)
    except CaseSystemError as exc:
        logger.warning("近日开庭明细获取失败: %s", exc)
        hearings = []
    items = [HearingOut(**vars(h)) for h in hearings]
    return HearingListOut(start=start, end=end, total=len(items), items=items)


@router.get("/card-cases", response_model=list[InternalCaseOut])
async def list_card_cases(
    key: str,
    include_pre_mediation: bool = False,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user),
) -> list[InternalCaseOut]:
    """总览卡片点开后对应的案件明细,口径与卡片计数共用 _row_in_card。

    排序与办案进度监控页一致:紧急度权重升序,同档内剩余天数越少越靠前。

    include_pre_mediation=True 且 key=due_reminders 时,额外并入案前调解的
    「临近/紧急」(进入调解满 30/45 天)案件——供 InfoWeb 时效提醒弹窗统一
    展示(自由列表、无表格列名冲突);面板总览「时效提醒」卡片不传此参数,
    案前调解仍单列在「案前调解」卡片。
    """
    if key not in _SNAPSHOT_CARD_KEYS:
        return []
    settings = await effective_settings(db)
    rows = await _snapshot_rows(db, settings)
    if rows is None:
        return []

    today = datetime.now(_LOCAL_TZ).date()
    bound_receive_ids = frozenset(await load_bound_receive_ids(db))
    if key == "pre_mediation":
        # 案前调解按"进入调解满 30/45 天"单独分档(compute_urgency 对 next_step=3
        # 同样走 compute_pre_mediation_urgency,这里直接复用,口径与卡片计数一致)。
        matched = [
            (compute_pre_mediation_urgency(row.raw_payload or {}, settings, today), row)
            for row, result in rows
            if is_pre_mediation(row) and row.external_case_id not in bound_receive_ids
        ]
    else:
        matched = [
            (result, row)
            for row, result in rows
            if _row_in_card(key, row, result.urgency, today, bound_receive_ids)
            or (
                include_pre_mediation
                and key == "due_reminders"
                and is_pre_mediation(row)
                and result.urgency in ("soon", "urgent")
                and row.external_case_id not in bound_receive_ids
            )
        ]
    items = await _build_case_list(db, matched)
    if key == "pending_receive":
        # 并入待录入内网的预登记案件(本地 SQLite),按同一套紧急度混排。
        virtual_items = [
            _virtual_case_out(v, settings, today)
            for v in await list_pending_virtual_cases()
        ]
        items.extend(virtual_items)
        items.sort(
            key=lambda c: (urgency_order(c.urgency), c.days_remaining is None, sort_days_key(c.urgency, c.days_remaining))
        )
    return items


def _last_12_months(today: date) -> list[str]:
    """近 12 个自然月的 YYYY-MM 列表(含当月,升序)。"""
    cursor = today.replace(day=1)
    months: list[str] = []
    for _ in range(12):
        months.append(cursor.strftime("%Y-%m"))
        cursor = (cursor - timedelta(days=1)).replace(day=1)
    return months[::-1]


@router.get("/charts", response_model=DashboardCharts)
async def get_dashboard_charts(
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user),
) -> DashboardCharts:
    """总览图表聚合,全部来自内网同步快照(与卡片同一数据源)。

    - monthly_trend: 近 12 个月立案数(handle 原生 handle_at)与结案数(end_at)。
    - open_steps: handle 环节未结案/未归档案件的 current_step 分布。
    - end_ways: 已结案案件的结案方式分布(调解/裁决/撤回/撤销)。
    - urgency: 在办案件紧急度分布(不含已结案 closed / 已退回 rejected,
      否则 2000+ 已结案会让在办的几十件完全看不见;案前调解也不计入)。
    快照为空时各字段返回空列表,前端显示"暂无数据"。
    """
    rows = await _snapshot_rows(db, await effective_settings(db))
    if rows is None:
        return DashboardCharts(monthly_trend=[], open_steps=[], end_ways=[], urgency=[])

    today = datetime.now(_LOCAL_TZ).date()
    months = _last_12_months(today)
    filed_by_month: Counter[str] = Counter()
    closed_by_month: Counter[str] = Counter()
    open_steps: Counter[str] = Counter()
    end_ways: Counter[str] = Counter()
    urgency_counts: Counter[str] = Counter()

    for row, result in rows:
        # 案前调解只在独立卡片跟踪,不进通用紧急度分布(其"紧急"是调解时长警告,
        # 非审理时限),否则 30 件案前调解会淹没"紧急"桶(2026-08-24)。
        if is_pre_mediation(row):
            continue
        if result.urgency not in ("closed", "rejected"):
            urgency_counts[result.urgency] += 1
        if row.stage != InternalStage.HANDLE:
            continue
        handle_at = (row.raw_payload or {}).get("handle_at")
        if isinstance(handle_at, str) and handle_at[:7] in months:
            filed_by_month[handle_at[:7]] += 1
        if row.current_step in (CLOSED_STEP, ARCHIVED_STEP):
            if row.end_at is not None:
                month = _as_local_date(row.end_at).strftime("%Y-%m")
                if month in months:
                    closed_by_month[month] += 1
            if row.end_way:
                end_ways[row.end_way] += 1
        else:
            open_steps[row.current_step or "未标注"] += 1

    return DashboardCharts(
        monthly_trend=[
            MonthlyTrendPoint(
                month=m,
                filed=filed_by_month.get(m, 0),
                closed=closed_by_month.get(m, 0),
            )
            for m in months
        ],
        open_steps=[NameCount(name=k, count=v) for k, v in open_steps.most_common()],
        end_ways=[NameCount(name=k, count=v) for k, v in end_ways.most_common()],
        urgency=[NameCount(name=k, count=v) for k, v in urgency_counts.most_common()],
    )


async def _build_case_list(
    db: AsyncSession,
    matched: list[tuple[UrgencyResult, InternalCaseTracking]],
) -> list[InternalCaseOut]:
    """排序(紧急度权重升序,同档剩余天数少的靠前;中止档位已中止天数久的靠前)并组装输出,卡片/图表明细共用。"""
    overrides = await _load_overrides(db)
    matched.sort(
        key=lambda item: (item[0].order, item[0].days_remaining is None, sort_days_key(item[0].urgency, item[0].days_remaining))
    )
    return [
        _build_out(
            row,
            overrides.get(row.external_case_id),
            result,
        )
        for result, row in matched
    ]


# 图表点开明细的维度:kind 与 /dashboard/charts、/stats/overview 的聚合一一对应。
_CHART_KINDS = (
    "filed_month", "closed_month", "open_step", "end_way", "urgency",
    "arbitrator", "duration_bucket", "over_limit_open", "over_limit_closed",
    "filed_year", "closed_year",
    "filed_stat_year", "closed_stat_year",
    "mediated_year", "mediated_stat_year",
    "withdrawal_year", "withdrawal_stat_year",
    "final_year", "final_stat_year",
)

# 年度数据区钻取的维度子集(立案/结案/调解/调撤/一裁终局 × 自然/统计年度)。
_YEAR_SCOPED_KINDS = (
    "filed_stat_year", "closed_stat_year",
    "mediated_year", "mediated_stat_year",
    "withdrawal_year", "withdrawal_stat_year",
    "final_year", "final_stat_year",
)


def _match_year_scoped(row: InternalCaseTracking, kind: str, value: str) -> bool:
    """年度数据区点开明细的过滤口径。

    kind 结尾带 _stat_year 时按统计年度(12-10~次年12-10,标签用结束年)过滤,
    否则按自然年度。立案看立案日期(handle_at),其余(结案/调解/调撤/一裁终局)
    看结案日期(end_at)且须已结案/归档;一裁终局 = end_way=裁决 且 end_way_detail
    ∈ {部分终局, 一裁终局},调撤 = 调解 + 撤回。
    """
    stat = kind.endswith("_stat_year")

    def year_of(d: date) -> int:
        return _stat_year(d) if stat else d.year

    if kind.startswith("filed_"):
        filed = _filed_date(row)
        return filed is not None and str(year_of(filed)) == value
    if row.current_step not in (CLOSED_STEP, ARCHIVED_STEP) or row.end_at is None:
        return False
    if str(year_of(_as_local_date(row.end_at))) != value:
        return False
    if kind.startswith("closed_"):
        return True
    if kind.startswith("mediated_"):
        return row.end_way == "调解"
    if kind.startswith("withdrawal_"):
        return row.end_way in ("调解", "撤回")
    if kind.startswith("final_"):
        return (
            row.end_way == "裁决"
            and _is_final_ruling((row.raw_payload or {}).get("end_way_detail"))
        )
    return False


@router.get("/chart-cases", response_model=list[InternalCaseOut])
async def list_chart_cases(
    kind: str,
    value: str,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user),
) -> list[InternalCaseOut]:
    """图表元素点开后对应的案件明细,过滤口径与 /dashboard/charts 的聚合一致。

    - filed_month/closed_month: value 为 YYYY-MM,分别按 handle_at / end_at 的月份过滤。
    - open_step: value 为 current_step(仅 handle 未结案/未归档)。
    - end_way: value 为结案方式(仅已结案/已归档)。
    - urgency: value 为紧急度(与图表一样不含 closed/rejected 与案前调解)。
    - arbitrator: value 为仲裁员姓名(handle 环节全部案件)。
    - duration_bucket: value 为审理时长分桶(≤45天/46-60天/61-90天/>90天,仅已结案/已归档)。
    - over_limit_open/over_limit_closed: 超审限案件(经过天数扣除中止 > 45天+延期),
      value 传任意值(不参与过滤)。
    - filed_stat_year/closed_stat_year/mediated_year/mediated_stat_year/withdrawal_year/
      withdrawal_stat_year/final_year/final_stat_year: 年度数据区钻取,按立案/结案日期
      所在自然年度或统计年度过滤(口径见 _match_year_scoped)。
    """
    if kind not in _CHART_KINDS:
        return []
    rows = await _snapshot_rows(db, await effective_settings(db))
    if rows is None:
        return []

    today = datetime.now(_LOCAL_TZ).date()

    def match(row: InternalCaseTracking, result: UrgencyResult) -> bool:
        if kind == "urgency":
            # 与 /dashboard/charts 聚合一致:案前调解不进通用紧急度分布。
            return result.urgency == value and not is_pre_mediation(row)
        if row.stage != InternalStage.HANDLE:
            return False
        if kind == "filed_month":
            handle_at = (row.raw_payload or {}).get("handle_at")
            return isinstance(handle_at, str) and handle_at[:7] == value
        if kind == "filed_year":
            handle_at = (row.raw_payload or {}).get("handle_at")
            return isinstance(handle_at, str) and handle_at[:4] == value
        if kind == "closed_year":
            return (
                row.current_step in (CLOSED_STEP, ARCHIVED_STEP)
                and row.end_at is not None
                and str(_as_local_date(row.end_at).year) == value
            )
        if kind in _YEAR_SCOPED_KINDS:
            return _match_year_scoped(row, kind, value)
        if kind == "closed_month":
            return (
                row.current_step in (CLOSED_STEP, ARCHIVED_STEP)
                and row.end_at is not None
                and _as_local_date(row.end_at).strftime("%Y-%m") == value
            )
        if kind == "open_step":
            if row.current_step in (CLOSED_STEP, ARCHIVED_STEP):
                return False
            return (row.current_step or "未标注") == value
        if kind == "arbitrator":
            return ((row.raw_payload or {}).get("arbitrator") or "未分配") == value
        if kind == "duration_bucket":
            duration = _case_duration_days(row)
            return duration is not None and _duration_bucket(duration) == value
        if kind == "over_limit_open":
            return (
                row.current_step not in (CLOSED_STEP, ARCHIVED_STEP)
                and _is_over_statutory_limit(row, today)
            )
        if kind == "over_limit_closed":
            return (
                row.current_step in (CLOSED_STEP, ARCHIVED_STEP)
                and _is_over_statutory_limit(row, today)
            )
        # end_way
        return row.current_step in (CLOSED_STEP, ARCHIVED_STEP) and (row.end_way or "") == value

    matched = [(result, row) for row, result in rows if match(row, result)]
    return await _build_case_list(db, matched)
