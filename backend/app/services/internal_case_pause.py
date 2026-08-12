"""内网案件中止天数回填。

内网列表接口不提供中止/恢复时间,但案件详情接口(POST case/caseData,与 InfoWeb
routes/handle.py 的立案详情同一个)返回 review_matter 审理事项记录,其中
"中止审理"/"恢复审理"条目带 approval_at(审批通过时间),两两配对即得中止区间。

回填策略:
- 存量:已结案/已归档且 paused_days 为空的案件,每轮一批、只取一次(结案时
  sync 会把在办期间留下的 paused_days 置回 None,这里按结案日精确重算);
- 增量:存量清零后,每轮重算全部在办案件(暂停仍在累计,ongoing 区间计到当天)。
新结案的案件由存量通道在后续轮次自动补上。单个案件失败记 warning 重试,
连续失败 _FETCH_FAIL_LIMIT 次按 0 落库放弃,不阻塞整批。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.case_system.client import (
    CaseSystemClient,
    CaseSystemError,
    get_case_system_client,
)
from app.models.internal_case import InternalCaseTracking, InternalStage
from app.services.internal_case_sync import SYNC_LOCK
from app.services.internal_case_urgency import ARCHIVED_STEP, CLOSED_STEP

logger = logging.getLogger(__name__)

_CASE_DATA_PATH = "/v1/api/admin/case/caseData"

# 业务本地时区(CST):结案日/"今天"都按本地自然日算,与 dashboard/stats 的口径一致,
# 避免服务器系统时区不是 CST 时在日界前后差 1 天。
_LOCAL_TZ = timezone(timedelta(hours=8))

# 每轮回填的案件数(单个案件一次 POST,对內网压力约等于翻一页列表)。
_BACKFILL_BATCH = 100
# 每件之间的间隔,进一步放缓回填速度。
_REQUEST_GAP_SECONDS = 0.2

# 单案详情连续失败上限:超过后按 0 落库放弃(防止必败案件让循环永远快节奏重试)。
_FETCH_FAIL_LIMIT = 3
_fetch_failures: dict[str, int] = {}

_PAUSE_STEP = "中止审理"
_RESUME_STEP = "恢复审理"

# 审限重新计算的事由(《劳动人事争议仲裁办案规则》:增加/变更仲裁请求、反申请、
# 追加当事人被受理后,仲裁期限重新起算)。变更仲裁庭组成人员/开庭安排不重启。
_CLOCK_RESET_STEPS = frozenset({"变更仲裁请求", "增加仲裁请求", "仲裁反申请", "追加当事人"})


def clock_reset_from_review_matter(review_matter: list | None) -> date | None:
    """最近一次审限重启日期;无重启记录返回 None(审限从立案日起算)。

    重启日以审批通过时间(approval_at)为准,无审批时间退用申请时间(created_at)。
    """
    reset: date | None = None
    for item in review_matter or []:
        if not isinstance(item, dict) or item.get("apply_matter") not in _CLOCK_RESET_STEPS:
            continue
        at = _parse_dt(item.get("approval_at")) or _parse_dt(item.get("created_at"))
        if at is not None and (reset is None or at.date() > reset):
            reset = at.date()
    return reset


def _parse_dt(value) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def paused_days_from_review_matter(
    review_matter: list | None,
    closed_at: date | None,
    today: date | None = None,
    since: date | None = None,
) -> int:
    """从 review_matter 配对中止/恢复审理,返回累计中止天数。

    只采纳已审批通过(approval_at 非空)的记录,以审批通过时间为生效时间;
    中止后无恢复的,以结案日(closed_at)为区间终点,未结案的在办案件以 today 计。
    since 非空时只统计与该日期之后重叠的中止区间(用于审限重启后:重启前的
    中止不参与重启后的审限扣减)。
    """
    today = today or datetime.now(_LOCAL_TZ).date()
    events: list[tuple[str, datetime]] = []
    for item in review_matter or []:
        if not isinstance(item, dict):
            continue
        matter = item.get("apply_matter")
        if matter not in (_PAUSE_STEP, _RESUME_STEP):
            continue
        approved_at = _parse_dt(item.get("approval_at"))
        if approved_at is None:
            continue
        events.append((matter, approved_at))
    events.sort(key=lambda e: e[1])

    total = 0
    pause_start: datetime | None = None

    def _accumulate(start: datetime, end: datetime) -> int:
        if since is not None:
            since_dt = datetime(since.year, since.month, since.day)
            if end <= since_dt:
                return 0
            start = max(start, since_dt)
        return max(0, (end - start).days)

    for matter, at in events:
        if matter == _PAUSE_STEP:
            if pause_start is None:  # 连续多次中止按最早一次计
                pause_start = at
        else:
            if pause_start is not None:
                total += _accumulate(pause_start, at)
                pause_start = None
    if pause_start is not None:
        end_date = closed_at or today
        end = datetime(end_date.year, end_date.month, end_date.day)
        total += _accumulate(pause_start, end)
    return total


async def _fetch_case_timing(
    client: CaseSystemClient, handle_row_id: str, closed_at: date | None
) -> tuple[int, date | None, int | None]:
    """取单个案件的 (全量中止天数, 最近审限重启日期, 重启后中止天数)。

    接口失败抛 CaseSystemError;无重启记录时第三项为 None。
    """
    resp = await client.post(_CASE_DATA_PATH, json={"id": handle_row_id})
    if resp.status_code != 200:
        raise CaseSystemError(f"case_data_http_{resp.status_code}")
    body = resp.json()
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        raise CaseSystemError("case_data_bad_body")
    review_matter = data.get("review_matter")
    reset = clock_reset_from_review_matter(review_matter)
    paused_after_reset = (
        paused_days_from_review_matter(review_matter, closed_at, since=reset)
        if reset is not None
        else None
    )
    return (paused_days_from_review_matter(review_matter, closed_at), reset, paused_after_reset)


async def backfill_paused_days(
    db: AsyncSession,
    client: CaseSystemClient | None = None,
    batch: int = _BACKFILL_BATCH,
) -> int:
    """回填/刷新中止天数,返回处理的存量件数(0 = 存量已清,转增量模式)。

    - 存量:已结案/已归档且 paused_days 为空的案件,每轮一批,只取一次。
    - 增量(存量清零后):在办案件的暂停仍在累计,每轮全量重算(量小,几十件),
       ongoing 的中止区间以今天为止。

    全程持有 internal_case_sync.SYNC_LOCK,与同步/对账互斥:并发时 sync 会用
    旧快照覆盖本循环刚算好的 paused_days(结案案件被算到"今天"而非结案日)。
    """
    async with SYNC_LOCK:
        return await _backfill_paused_days(db, client, batch)


async def _backfill_paused_days(
    db: AsyncSession,
    client: CaseSystemClient | None = None,
    batch: int = _BACKFILL_BATCH,
) -> int:
    client = client or get_case_system_client()
    stmt = (
        select(InternalCaseTracking)
        .where(
            InternalCaseTracking.stage == InternalStage.HANDLE,
            InternalCaseTracking.current_step.in_([CLOSED_STEP, ARCHIVED_STEP]),
            InternalCaseTracking.paused_days.is_(None),
        )
        .order_by(InternalCaseTracking.created_at)
        .limit(batch)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    is_backlog = bool(rows)
    if not rows:
        stmt = select(InternalCaseTracking).where(
            InternalCaseTracking.stage == InternalStage.HANDLE,
            InternalCaseTracking.current_step.not_in([CLOSED_STEP, ARCHIVED_STEP]),
        )
        rows = list((await db.execute(stmt)).scalars().all())

    done = 0
    for row in rows:
        handle_row_id = (row.raw_payload or {}).get("id")
        if handle_row_id is None:
            # 快照缺内网行 id,无法查详情;按 0 落库避免每轮重复打捞。
            row.paused_days = 0
            done += 1
            continue
        closed_at = None
        if row.end_at is not None:
            # end_at 带时区(UTC 存储),统一转 CST 日期,与审理时长/超审限的口径一致。
            closed_at = (
                row.end_at.astimezone(_LOCAL_TZ).date()
                if row.end_at.tzinfo is not None
                else row.end_at.date()
            )
        try:
            (
                row.paused_days,
                row.clock_reset_at,
                row.paused_after_reset_days,
            ) = await _fetch_case_timing(client, str(handle_row_id), closed_at)
            _fetch_failures.pop(row.external_case_id, None)
            done += 1
        except CaseSystemError as exc:
            fails = _fetch_failures.get(row.external_case_id, 0) + 1
            _fetch_failures[row.external_case_id] = fails
            if fails >= _FETCH_FAIL_LIMIT:
                logger.warning("回填中止天数连续失败 %d 次,按 0 落库放弃(case %s): %s", fails, row.case_no, exc)
                row.paused_days = 0
                _fetch_failures.pop(row.external_case_id, None)
                done += 1
            else:
                logger.warning("回填中止天数失败(case %s,第 %d 次): %s", row.case_no, fails, exc)
        await asyncio.sleep(_REQUEST_GAP_SECONDS)
    if done:
        logger.info("中止天数%s:本轮处理 %d 件", "回填" if is_backlog else "在办刷新", done)
    # 返回值只计存量,驱动主循环的"存量未清→跑快些"节奏;在办刷新不占用该信号。
    return done if is_backlog else 0
