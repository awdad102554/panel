"""内网案件同步服务。

同步分两种模式(2026-07-30 起,此前每轮都是全量):
- 全量(full): 从内网 3 个环节接口 arb/{reserve,receive,handle} 全量翻页拉取。
  仅作手工恢复手段(初次建快照、数据严重不一致时),日常不跑。
- 轻量(light): 内网接口实测支持筛选——receive?status=0 只回待审核、
  handle?status=未结案 只回在办、按 application_date 补抓今天+昨天的新收件/
  新立案(个位数条)。已结案案件信息不再变动,不重复翻页拉取;"快速流转"案件
  (提交后很快被处理、立案当天即结案)由日期补抓捕获;对"上一轮还在办、本轮
  消失"的案件用 case_no 单点补拉(结案/退回状态翻转的捕获)。每轮约 7 次小请求
  (替代 ~46 页全量),日常循环只用轻量。

同步顺序 reserve → receive → handle:同一个 case_id 可能同时出现在多个环节的返回里
(receive/reserve 返回的是未过滤列表,不是"当前仍停留在该环节"的过滤列表;reserve 审核通过
即离开列表,只留待审核/退回补正记录),后处理的 handle
覆盖前者,最终 stage 反映案件真实所处的最靠后环节。

单个环节请求失败只记 warning、跳过该环节,不影响其余环节(仿 CaseSystemStatsService 的容错风格)。
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.case_system.client import (
    CaseSystemClient,
    CaseSystemError,
    get_case_system_client,
)
from app.models.internal_case import (
    CaseTimeLimitOverride,
    InternalCaseTracking,
    InternalStage,
    SyncVerificationReport,
)
from app.services.internal_case_urgency import ARCHIVED_STEP, CLOSED_STEP

logger = logging.getLogger(__name__)

_PAGE_SIZE = 100
# 翻页保险丝:上游忽略 page 参数或 totalNum 异常时,翻页循环可能永不终止,
# 超过该页数直接判失败(抛 CaseSystemError,该环节跳过)。
_PAGE_LIMIT = 500

# 同步/对账/中止天数回填互斥锁(模块级一把,单 worker):并发会让结案案件的
# paused_days 被旧值覆盖固化、已删快照被并发同步复活并丢失人工时效覆盖
# (2026-08-12 审查发现)。后台循环用 locked() 检查跳过本轮,手动端点返回 409。
SYNC_LOCK = asyncio.Lock()

# 内网系统时间戳是无时区的本地时间(CST, UTC+8),解析后需显式带上时区,
# 否则存入 DateTime(timezone=True) 列时会被当成 UTC,导致天数计算偏差 8 小时。
_INTRANET_TZ = timezone(timedelta(hours=8))


def _utc_now() -> datetime:
    """带时区的当前 UTC 时间。

    不能用 datetime.utcnow():它返回 naive datetime,写入 DateTime(timezone=True)
    列时会被驱动按本地时区(CST)解释再换算,使存下的 UTC 值凭空偏移 8 小时。
    """
    return datetime.now(timezone.utc)


# 环节接口路径与额外必填参数(reserve 需要 type=1,实测为内网唯一在用的取值)。
_STAGE_SPECS: list[tuple[InternalStage, str, dict]] = [
    (InternalStage.RESERVE, "/v1/api/admin/arb/reserve", {"type": 1}),
    (InternalStage.RECEIVE, "/v1/api/admin/arb/receive", {}),
    (InternalStage.HANDLE, "/v1/api/admin/arb/handle", {}),
]

# 轻量同步的筛选参数(2026-07-30 对内网实测):receive?status=0 只回待审核、
# handle?status=未结案 只回在办(含中止),已结案的 2100+ 件不再重复拉取。
_STAGE_SPECS_LIGHT: list[tuple[InternalStage, str, dict]] = [
    (InternalStage.RESERVE, "/v1/api/admin/arb/reserve", {"type": 1}),
    (InternalStage.RECEIVE, "/v1/api/admin/arb/receive", {"status": "0"}),
    (InternalStage.HANDLE, "/v1/api/admin/arb/handle", {"status": "未结案"}),
]

_STAGE_PATHS = {stage: path for stage, path, _ in _STAGE_SPECS}

_CASE_NO_KEY_RE = re.compile(r"\[(\d{4})\](\d+)")


def _parse_dt(value) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=_INTRANET_TZ)
        except ValueError:
            continue
    return None


def _parse_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None


def _parse_time_limit_days(value) -> int | None:
    """解析内网中文剩余天数文案,统一成"负数=已超期"语义。

    receive.receive_time_limit 形如 "4天"(剩4天)或 "超期1044天"(已超期1044天)。
    返回:剩余=正数、超期=负数、无法解析(空串/"已结案"等)→None。
    """
    if not value:
        return None
    text = str(value).strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    days = int(digits)
    return -days if "超期" in text else days


async def _fetch_stage_records(
    client: CaseSystemClient, path: str, extra: dict
) -> list[dict]:
    """翻页拉取某环节的全量记录。"""
    records: list[dict] = []
    page = 1
    while True:
        params = {"page": page, "page_size": _PAGE_SIZE, **extra}
        resp = await client.get(path, params=params)
        if resp.status_code != 200:
            raise CaseSystemError(f"{path}_http_{resp.status_code}")
        try:
            body = resp.json()
        except ValueError as exc:
            # 上游 200 返回 HTML 等非 JSON 时 resp.json() 抛 ValueError,统一成
            # CaseSystemError,避免穿透成 500/误判"远端为空"。
            raise CaseSystemError(f"{path}_bad_json") from exc
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            raise CaseSystemError(f"{path}_bad_body")
        batch = data.get("data") or data.get("list") or []
        records.extend(batch)
        total = data.get("totalNum")
        if not batch or (isinstance(total, int) and page * _PAGE_SIZE >= total):
            break
        page += 1
        if page > _PAGE_LIMIT:
            raise CaseSystemError(f"{path}_page_overflow")
    return records


async def _fetch_first_page(
    client: CaseSystemClient, path: str, extra: dict
) -> list[dict]:
    """只拉某环节的第一页(轻量同步的日期补抓用;不带日期参数时按时间倒序取最新)。"""
    resp = await client.get(path, params={"page": 1, "page_size": _PAGE_SIZE, **extra})
    if resp.status_code != 200:
        raise CaseSystemError(f"{path}_http_{resp.status_code}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise CaseSystemError(f"{path}_bad_json") from exc
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        raise CaseSystemError(f"{path}_bad_body")
    return data.get("data") or data.get("list") or []


async def _fetch_single_by_case_no(
    client: CaseSystemClient,
    stage: InternalStage,
    case_no: str | None,
    expected_case_id: str | None = None,
) -> dict | None:
    """按案号单点补拉一条记录(轻量同步里捕获结案/退回的状态翻转)。

    内网 case_no 查询参数只认 "[2025]427" 这种核心格式(与 InfoWeb 立案查询的
    转换逻辑一致),需从完整案号里提取。查不到返回 None。
    expected_case_id 传入时校验返回记录的 case_id,防止案号模糊匹配串案。
    """
    if not case_no:
        return None
    # stage 可能是快照读回的字符串(列是 String):_STAGE_PATHS 查表靠 str 枚举
    # hash/eq 能命中,但下方错误分支的 stage.value 对纯 str 会 AttributeError
    # 穿透 except CaseSystemError(与 _map_record 同根因,2026-08-12 终审发现)。
    stage = InternalStage(stage)
    match = _CASE_NO_KEY_RE.search(case_no)
    if match is None:
        return None
    key = f"[{match.group(1)}]{match.group(2)}"
    resp = await client.get(
        _STAGE_PATHS[stage], params={"page": 1, "page_size": 5, "case_no": key}
    )
    if resp.status_code != 200:
        raise CaseSystemError(f"{stage.value}_single_http_{resp.status_code}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise CaseSystemError(f"{stage.value}_single_bad_json") from exc
    data = body.get("data") if isinstance(body, dict) else None
    batch = (data.get("data") or data.get("list") or []) if isinstance(data, dict) else []
    if expected_case_id is None:
        return batch[0] if batch else None
    # 案号核心格式是模糊匹配(如 "[2025]427" 可能命中 4270),在返回的整页里
    # 按 case_id 定位目标记录,不能只看首条——目标在 batch[1+] 时只看首条会
    # 误判"未查到",把 receive→handle 补拉路径的案件冻结在收件环节。
    for raw in batch:
        if str(raw.get("case_id")) == expected_case_id:
            return raw
    if batch:
        logger.warning("单点补拉案号 %s 的返回里没有目标 case_id,按未查到处理", case_no)
    return None


def _payload_dates(raw_payload: dict) -> list[date]:
    """候选申请/收件日期(去重,优先级序):application_at / receive_at / created_at。

    内网 application_date 过滤按哪个字段过滤是黑盒,且工作人员可能改申请日期,
    单一日期键 + ±1 天窗口存在"案件还在但探测不到"的误删路径(2026-08-10 复查发现),
    故取三个键的并集逐日探测。
    """
    days: list[date] = []
    for key in ("application_at", "receive_at", "created_at"):
        dt = _parse_dt((raw_payload or {}).get(key))
        if dt is not None and dt.date() not in days:
            days.append(dt.date())
    return days


async def _probe_receive_by_date(
    client: CaseSystemClient, ext_id: str, raw_payload: dict
) -> dict | None:
    """无案号 receive 案件的定点探测:按候选日期(各 ±1 天窗口)拉收件记录,按 case_id 定位。

    "保存未审批"的收件没有正式案号(案号字段是哈希串),案号探测无效;但 case_id
    稳定、申请日期已知,且 receive 接口的 application_date 过滤返回各状态记录
    (日期补抓已实测验证),借此区分"已处理/已修改"(找到)与"内网已删除"(找不到)。
    找到返回记录;找不到返回 None;请求失败抛 CaseSystemError。
    """
    days = _payload_dates(raw_payload)
    if not days:
        return None
    probe_days = sorted({d + timedelta(days=off) for d in days for off in (0, -1, 1)})
    for day in probe_days:
        records = await _fetch_stage_records(
            client,
            _STAGE_PATHS[InternalStage.RECEIVE],
            {"application_date": day.isoformat()},
        )
        for raw in records:
            if str(raw.get("case_id")) == ext_id:
                return raw
    return None


def _phase_anchor_fallback(stage: InternalStage, raw: dict) -> datetime:
    """首次见到某案件时,用该环节最接近的原生时间戳作为进入当前环节的锚点。"""
    if stage is InternalStage.RESERVE:
        candidates = (raw.get("reserve_at"), raw.get("submit_at"), raw.get("created_at"))
    elif stage is InternalStage.RECEIVE:
        candidates = (raw.get("receive_at"), raw.get("application_at"), raw.get("created_at"))
    else:  # HANDLE
        candidates = (raw.get("handle_at"), raw.get("created_at"))
    for c in candidates:
        dt = _parse_dt(c)
        if dt is not None:
            return dt
    return _utc_now()


def _map_record(stage: InternalStage, raw: dict) -> dict:
    """把内网原始记录映射成 InternalCaseTracking 字段(不含 phase_entered_at)。"""
    # stage 可能是快照读回的字符串(列是 String,见 _refetch_disappeared 的 prev.stage);
    # 下面用 is 判枚举单例,字符串会全部落空——结案/结案方式等字段静默变 None
    # (2026-08-12 全量校验发现:在办→结案翻转经补拉后 raw 已新但列不更新)。
    stage = InternalStage(stage)
    external_case_id = str(raw.get("case_id"))
    case_no = raw.get("case_no")
    current_step = None
    is_paused = False
    native_remaining_days: int | None = None
    end_at = None
    end_way = None

    if stage is InternalStage.HANDLE:
        current_step = raw.get("current_step")
        is_paused = _parse_int(raw.get("stop")) == 1
        # closing_time_limit 是剩余审理天数;结案后为字符串"已结案",转 int 失败→None。
        native_remaining_days = _parse_int(raw.get("closing_time_limit"))
        # 内网的 closing_time_limit 不包含已批准的延期(工作人员 2026-07-27 确认),
        # 需自行加上 extension_days 才是真实剩余天数(如 3 天审限 + 15 天延期 = 18 天)。
        extension = _parse_int(raw.get("extension_days")) or 0
        if native_remaining_days is not None and extension > 0:
            native_remaining_days += extension
        end_at = _parse_dt(raw.get("end_at"))
        end_way = raw.get("end_way")
    elif stage is InternalStage.RESERVE:
        # 预约待审核自带 reserve_time_limit(中文文案,与 receive_time_limit 同格式,
        # 如 "2天"/"超期3天"),优先解析成统一的剩余天数(负数=超期)。
        native_remaining_days = _parse_time_limit_days(raw.get("reserve_time_limit"))
        if native_remaining_days is None:
            # 兜底:overdue_days>0 转负数,统一"负数=已超期"语义,
            # 与 handle 的 closing_time_limit 一套读取逻辑。
            overdue = _parse_int(raw.get("overdue_days"))
            native_remaining_days = -overdue if overdue and overdue > 0 else None
    elif stage is InternalStage.RECEIVE:
        # 收件自带 receive_time_limit(中文文案),解析成统一的剩余天数(负数=超期)。
        native_remaining_days = _parse_time_limit_days(raw.get("receive_time_limit"))

    return {
        "external_case_id": external_case_id,
        "stage": stage,
        "current_step": current_step,
        "case_no": case_no if isinstance(case_no, str) else (str(case_no) if case_no else None),
        "is_paused": is_paused,
        "native_remaining_days": native_remaining_days,
        "end_at": end_at,
        "end_way": end_way if isinstance(end_way, str) else None,
        "raw_payload": raw,
    }


# 环节优先级:同一案件出现在多个环节时,以优先级高(更靠后)的环节为准。
# 不能靠写入顺序——轻量同步的补页(最新收件/最新结案)在筛选结果之后合并,
# 顺序覆盖会把"已立案"的案件错误打回"收件"(2026-08-06 校验发现的 76 件错标)。
_STAGE_PRIORITY = {InternalStage.RESERVE: 0, InternalStage.RECEIVE: 1, InternalStage.HANDLE: 2}


def _merge_by_priority(merged: dict[str, dict], mapped: dict) -> None:
    ext_id = mapped["external_case_id"]
    prev = merged.get(ext_id)
    if prev is None or _STAGE_PRIORITY[mapped["stage"]] >= _STAGE_PRIORITY[prev["stage"]]:
        merged[ext_id] = mapped


async def sync_internal_cases(
    db: AsyncSession, client: CaseSystemClient | None = None, *, full: bool = True
) -> dict[str, int]:
    """同步内网案件到本地快照表。返回各环节抓取条数(轻量模式含补抓/补拉件数)。

    full=True  全量翻页(仅手工恢复用,日常不跑);full=False 轻量(筛选接口
    + 日期补抓 + 消失案件单点补拉)。

    全程持有模块级 SYNC_LOCK,与对账/中止天数回填互斥:并发会让结案案件的
    paused_days 被旧值覆盖固化、已删快照被并发同步复活并丢失人工时效覆盖
    (2026-08-12 审查发现)。
    """
    async with SYNC_LOCK:
        return await _sync_internal_cases(db, client, full=full)


async def _sync_internal_cases(
    db: AsyncSession, client: CaseSystemClient | None = None, *, full: bool = True
) -> dict[str, int]:
    client = client or get_case_system_client()

    # 预加载同步前的现有快照,用于判断 (stage, current_step) 是否变化以维护 phase_entered_at,
    # 轻量模式下还用于发现"上一轮还在办、本轮消失"的案件。
    existing: dict[str, InternalCaseTracking] = {}
    result = await db.execute(select(InternalCaseTracking))
    for row in result.scalars().all():
        existing[row.external_case_id] = row

    # 按顺序抓取并归并:后面的环节覆盖前面的,最终每个 case_id 落在最靠后的环节。
    specs = _STAGE_SPECS if full else _STAGE_SPECS_LIGHT
    merged: dict[str, dict] = {}
    counts: dict[str, int] = {}
    fetched_stages: set[InternalStage] = set()
    for stage, path, extra in specs:
        try:
            records = await _fetch_stage_records(client, path, extra)
        except CaseSystemError as exc:
            logger.warning("内网环节 %s 同步失败,跳过: %s", stage.value, exc)
            counts[stage.value] = 0
            continue
        fetched_stages.add(stage)
        counts[stage.value] = len(records)
        for raw in records:
            if raw.get("case_id") is None:
                continue
            mapped = _map_record(stage, raw)
            _merge_by_priority(merged, mapped)

    deleted_ids: list[str] = []
    if full and len(fetched_stages) == len(_STAGE_SPECS):
        # 全量模式下 3 个环节拉的都是全量历史,快照多出=内网已删除,顺手清理
        # (轻量模式的清理走消失检测)。
        # 任一环节拉取失败则跳过清理,防止把"没拉到"误判成"已删除"。
        deleted_ids = [
            ext_id
            for ext_id, prev in existing.items()
            if ext_id not in merged
            and prev.stage in (InternalStage.RESERVE, InternalStage.RECEIVE, InternalStage.HANDLE)
        ]
        if deleted_ids:
            counts["deleted"] = len(deleted_ids)
            logger.info("全量同步清理内网已删除案件的快照: %d 件", len(deleted_ids))
    if not full:
        # 按日期补抓(2026-08-06 实测内网支持 application_date 过滤):今天+昨天的
        # 新收件/新立案各拉一次(每次通常个位数条)。捕获"快速流转"案件——提交后
        # 很快被处理、从未出现在 status=0 筛选结果里的收件(如实测 263 号案件),
        # 以及"立案当天即结案"等从未出现在在办列表里的案件;消失检测对它们无效
        # (快照里还没有它们)。用今天+昨天两天,覆盖跨午夜处理的边界。
        recent_dates = [
            datetime.now(_INTRANET_TZ).date(),
            (datetime.now(_INTRANET_TZ) - timedelta(days=1)).date(),
        ]
        for stage, count_key in (
            (InternalStage.RECEIVE, "receive_recent"),
            (InternalStage.HANDLE, "handle_recent"),
        ):
            fetched = 0
            for day in recent_dates:
                try:
                    records = await _fetch_first_page(
                        client, _STAGE_PATHS[stage], {"application_date": day.isoformat()}
                    )
                except CaseSystemError as exc:
                    logger.warning("内网 %s %s 补抓失败,跳过: %s", stage.value, day, exc)
                    continue
                fetched += len(records)
                for raw in records:
                    if raw.get("case_id") is None:
                        continue
                    mapped = _map_record(stage, raw)
                    if stage is InternalStage.HANDLE:
                        # 罕见但存在:结案后重新开庭恢复在办,会同时出现在在办筛选和
                        # 日期补抓里,以在办为准(已在 merged 里的 handle 记录不覆盖)。
                        prev = merged.get(mapped["external_case_id"])
                        if prev is not None and prev["stage"] is InternalStage.HANDLE:
                            continue
                    _merge_by_priority(merged, mapped)
            counts[count_key] = fetched

        counts["refetched"], deleted_ids = await _refetch_disappeared(
            client, existing, merged, reserve_complete=InternalStage.RESERVE in fetched_stages
        )
        if deleted_ids:
            counts["deleted"] = len(deleted_ids)

    now = _utc_now()
    rows: list[dict] = []
    newly_closed_ids: list[str] = []
    for ext_id, mapped in merged.items():
        prev = existing.get(ext_id)
        if prev is None:
            phase_entered_at = _phase_anchor_fallback(mapped["stage"], mapped["raw_payload"])
        elif (
            prev.stage == mapped["stage"]
            and prev.current_step == mapped["current_step"]
            and prev.is_paused == mapped["is_paused"]
        ):
            phase_entered_at = prev.phase_entered_at  # 环节/子状态/中止标志未变,锚点保持
        else:
            # 环节/子状态/中止标志变化,以本轮同步时刻为近似锚点。
            # is_paused 翻转必须重置:紧急度按锚点算"已中止XX天"(internal_case_urgency),
            # 内网只把 stop 置 1 而 current_step 不变时,不重置会高估中止时长。
            phase_entered_at = now
        rows.append({**mapped, "phase_entered_at": phase_entered_at, "last_synced_at": now})
        # 在办→已结案/已归档:中止天数需按结案日重算(在办期间是按"算到当天"留下的),
        # 置回 None,由 internal_case_pause 的存量通道下一轮精确重算。
        if (
            prev is not None
            and prev.stage == InternalStage.HANDLE
            and prev.current_step not in (CLOSED_STEP, ARCHIVED_STEP)
            and mapped["current_step"] in (CLOSED_STEP, ARCHIVED_STEP)
            and prev.paused_days is not None
        ):
            newly_closed_ids.append(ext_id)

    if rows:
        stmt = insert(InternalCaseTracking).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[InternalCaseTracking.external_case_id],
            set_={
                "stage": stmt.excluded.stage,
                "current_step": stmt.excluded.current_step,
                "case_no": stmt.excluded.case_no,
                "is_paused": stmt.excluded.is_paused,
                "native_remaining_days": stmt.excluded.native_remaining_days,
                "end_at": stmt.excluded.end_at,
                "end_way": stmt.excluded.end_way,
                "phase_entered_at": stmt.excluded.phase_entered_at,
                "raw_payload": stmt.excluded.raw_payload,
                "last_synced_at": stmt.excluded.last_synced_at,
            },
        )
        await db.execute(stmt)

    if newly_closed_ids:
        await db.execute(
            update(InternalCaseTracking)
            .where(InternalCaseTracking.external_case_id.in_(newly_closed_ids))
            .values(paused_days=None)
        )
        logger.info("检测到 %d 件案件结案,paused_days 已重置待按结案日重算", len(newly_closed_ids))

    if deleted_ids:
        # 内网侧已删除的案件(轻量:日期窗口探测确认;全量:全量历史比对),清理快照,
        # 连带清掉同 id 的人工时效覆盖(override 表无 FK,不连带会留孤儿行,
        # 内网若重建同 case_id 案件,旧覆盖会静默生效)。
        await db.execute(
            delete(InternalCaseTracking).where(
                InternalCaseTracking.external_case_id.in_(deleted_ids)
            )
        )
        await db.execute(
            delete(CaseTimeLimitOverride).where(
                CaseTimeLimitOverride.external_case_id.in_(deleted_ids)
            )
        )
        logger.info("清理内网已删除案件的快照: %d 件 %s", len(deleted_ids), deleted_ids)

    logger.info("内网案件同步(%s):抓取 %s,合并落库 %d 条", "全量" if full else "轻量", counts, len(rows))
    return counts


async def _refetch_disappeared(
    client: CaseSystemClient,
    existing: dict[str, InternalCaseTracking],
    merged: dict[str, dict],
    *,
    reserve_complete: bool,
) -> tuple[int, list[str]]:
    """轻量同步:补拉"上一轮还在办、本轮不在筛选结果里"的案件。

    这些案件多半是状态翻转:handle 在办→已结案、receive 待审核→已处理(立案或退回)。
    已结案/已归档、receive 已处理(status!=0)的快照行本就不再变化,不在检测范围。

    探测手段(按优先级):
    - 案号单点补拉(有正式案号的案件);
    - receive 无案号(哈希案号)案件退到"申请日期±1天 + case_id"定点探测
      (_probe_receive_by_date):找到=已处理/已修改,更新快照;窗口内找不到=
      内网已删除,删除快照行(误删代价低,全量同步可恢复)。
    探测请求失败的保留快照原值下轮重试,宁可不删。

    reserve 环节单独处理:轻量同步对 reserve 是全量拉取(无筛选),本轮拉取成功
    (reserve_complete)而快照行不在返回里 = 已审核离开预约环节(转收件,内网可能
    另建新 case_id)或内网已删除。预约无案号(案号字段为空)无法单点探测,直接
    删除快照(误删可用全量同步恢复);转收件后的案件由 receive 侧同步自然捕获。
    reserve 拉取失败时保留原值下轮重试。

    返回 (补拉更新件数, 判定删除的 external_case_id 列表)——删除由调用方落库。
    """
    refetched = 0
    deleted_ids: list[str] = []
    for ext_id, prev in existing.items():
        if ext_id in merged:
            continue
        if prev.stage == InternalStage.HANDLE:
            if prev.current_step in (CLOSED_STEP, ARCHIVED_STEP):
                continue
        elif prev.stage == InternalStage.RECEIVE:
            if (prev.raw_payload or {}).get("status") != 0:
                continue
        else:
            # reserve:全量拉取成功时,消失=已离开预约环节或内网已删除,删除快照。
            if not reserve_complete:
                continue
            deleted_ids.append(ext_id)
            logger.info(
                "预约案件 %s 已离开预约列表(审核转收件或内网删除),删除快照", ext_id
            )
            continue
        try:
            raw = await _fetch_single_by_case_no(
                client, prev.stage, prev.case_no, expected_case_id=ext_id
            )
        except CaseSystemError as exc:
            logger.warning("补拉案件 %s 失败: %s", prev.case_no, exc)
            continue
        if prev.stage == InternalStage.RECEIVE and raw is None:
            # 案号探测无效(无案号/未查到):按申请日期+case_id 定点探测,区分删除与已处理。
            try:
                raw = await _probe_receive_by_date(client, ext_id, prev.raw_payload or {})
            except CaseSystemError as exc:
                logger.warning(
                    "补拉案件 %s 按日期探测失败,保留快照原值下轮重试: %s", prev.case_no, exc
                )
                continue
            if raw is None:
                if not _payload_dates(prev.raw_payload or {}):
                    # 取不到申请日期就无法探测,"找不到"和"无法找"必须区分——
                    # 后者判删除会误删(2026-08-10 自检发现)。
                    logger.warning(
                        "补拉案件 %s 的快照缺少申请日期,无法定点探测,保留原值", prev.case_no
                    )
                    continue
                deleted_ids.append(ext_id)
                logger.info(
                    "补拉案件 %s 在内网已删除(日期窗口探测无记录),删除快照", prev.case_no
                )
                continue
        if raw is None or raw.get("case_id") is None:
            logger.warning("补拉案件 %s 未查到,保留快照原值", prev.case_no)
            continue
        mapped = _map_record(prev.stage, raw)
        if prev.stage == InternalStage.RECEIVE and (raw.get("status") or 0) != 0:
            # receive 待审核案件已处理(立案/退回):可能已流转 handle,甚至老申请
            # 集中处理后立案当天结案(不在日期补抓窗口内)。再探一次 handle,
            # 否则快照会冻结在 receive 直到人工全量同步(2026-08-10 审查发现)。
            # 案号优先用探测到的最新记录里的——保存后正式提交会获得正式收字号,
            # 用快照里的哈希案号探 handle 会被正则短路,防冻结逻辑形同虚设
            # (2026-08-10 复查发现)。
            probe_case_no = raw.get("case_no") or prev.case_no
            try:
                handle_raw = await _fetch_single_by_case_no(
                    client, InternalStage.HANDLE, probe_case_no, expected_case_id=ext_id
                )
            except CaseSystemError as exc:
                # handle 探测失败不能落 receive 结果:若案件其实"立案当天已结案",
                # 落了 receive 已处理后下轮补拉会被 status!=0 跳过,快照永久冻结。
                # 保留快照原值,下轮重试(2026-08-10 复查发现)。
                logger.warning("补拉案件 %s 的 handle 环节失败,保留快照原值下轮重试: %s", prev.case_no, exc)
                continue
            if handle_raw is not None and handle_raw.get("case_id") is not None:
                mapped = _map_record(InternalStage.HANDLE, handle_raw)
            # handle 明确未查到(无异常):基本等价于"退回/不同意",落 receive 结果。
        merged[ext_id] = mapped
        refetched += 1
        logger.info(
            "补拉案件 %s:%s → %s",
            prev.case_no,
            # stage 列是 String,读回为 str;mapped 的 stage 可能是枚举也可能是 str,统一取值。
            prev.current_step or str(prev.stage),
            mapped["current_step"] or getattr(mapped["stage"], "value", mapped["stage"]),
        )
    return refetched, deleted_ids


# 一致性校验比对的字段(阶段/子状态/结案信息;剩余天数每天自然变化,不比)。
_VERIFY_FIELDS = ("current_step", "end_way", "is_paused")
_VERIFY_LIST_CAP = 50  # 接口返回的差异列表上限
_VERIFY_DETAILS_CAP = 500  # 落库明细上限(防极端情况报告过大)


async def verify_consistency(
    db: AsyncSession, client: CaseSystemClient | None = None
) -> dict:
    """全量只读对账:拉取内网 3 个环节全量数据,与快照逐案比对,不修正数据。

    用于验证轻量同步是否有遗漏(2026-07-31 起全量退出日常机制后的校验手段)。
    每次校验的统计与完整差异明细落库到 sync_verification_reports(由调用方提交),
    供事后排查轻量同步的问题。全程持有 SYNC_LOCK,与同步/中止回填互斥。

    返回:
    - checked: 内网全量案件数
    - missing_in_snapshot: 内网有但快照缺失(轻量同步漏同步)
    - field_mismatches: 两边都有但 阶段/子状态/结案字段 不一致(轻量同步没跟上)
    - only_in_snapshot: 快照有但内网全量未返回的条数(通常无害,仅计数)
    - stage_errors: 抓取失败被跳过的环节及原因(失败的环节不参与比对,绝不把
      "没拉到"当成"远端为空"误报本地缺失)
    返回的差异列表各最多 50 条;落库明细各最多 500 条。
    """
    async with SYNC_LOCK:
        return await _verify_consistency(db, client)


async def _verify_consistency(
    db: AsyncSession, client: CaseSystemClient | None = None
) -> dict:
    client = client or get_case_system_client()
    existing: dict[str, InternalCaseTracking] = {}
    result = await db.execute(select(InternalCaseTracking))
    for row in result.scalars().all():
        existing[row.external_case_id] = row

    merged: dict[str, dict] = {}
    stage_errors: list[str] = []
    for stage, path, extra in _STAGE_SPECS:
        try:
            records = await _fetch_stage_records(client, path, extra)
        except CaseSystemError as exc:
            # 抓取失败绝不能当成"远端为空"——会把该环节全部案件误报为本地缺失,
            # 记入 stage_errors 并跳过该环节的比对。
            logger.warning("一致性校验环节 %s 抓取失败,跳过该环节比对: %s", stage.value, exc)
            stage_errors.append(f"{stage.value}: {exc}")
            continue
        for raw in records:
            if raw.get("case_id") is None:
                continue
            mapped = _map_record(stage, raw)
            _merge_by_priority(merged, mapped)

    missing: list[dict] = []
    mismatches: list[dict] = []
    missing_total = 0
    mismatch_total = 0
    for ext_id, expected in merged.items():
        prev = existing.get(ext_id)
        if prev is None:
            missing_total += 1
            if len(missing) < _VERIFY_DETAILS_CAP:
                missing.append(
                    {
                        "case_no": expected["case_no"],
                        "stage": expected["stage"].value,
                        "current_step": expected["current_step"],
                    }
                )
            continue
        # stage 列是 String,读回为 str;expected 是枚举,统一按 .value 比较。
        if prev.stage != expected["stage"].value:
            mismatch_total += 1
            if len(mismatches) < _VERIFY_DETAILS_CAP:
                mismatches.append(
                    {
                        "case_no": prev.case_no,
                        "field": "stage",
                        "snapshot": str(prev.stage),
                        "intranet": expected["stage"].value,
                    }
                )
            continue  # 环节都不同了,子状态不再逐项比
        # receive/reserve 环节加比内网 status(不在 _VERIFY_FIELDS 里):"保存未审批"的收件
        # 被退回/处理后,环节和子状态都不变,只有 raw_payload.status 变化(2026-08-10
        # 实测陈宁娥案:快照停在待审核,校验此前报不出来);预约待审核被退回(0→2)同理。
        if expected["stage"] in (InternalStage.RECEIVE, InternalStage.RESERVE):
            # 两侧都过 _parse_int:快照 JSONB 里是 int,内网若返回字符串 "0" 不致噪声。
            snap_status = _parse_int((prev.raw_payload or {}).get("status"))
            net_status = _parse_int((expected["raw_payload"] or {}).get("status"))
            if snap_status != net_status:
                mismatch_total += 1
                if len(mismatches) < _VERIFY_DETAILS_CAP:
                    mismatches.append(
                        {
                            "case_no": prev.case_no,
                            "field": f"{expected['stage'].value}_status",
                            "snapshot": snap_status,
                            "intranet": net_status,
                        }
                    )
        for field in _VERIFY_FIELDS:
            if getattr(prev, field) != expected[field]:
                mismatch_total += 1
                if len(mismatches) < _VERIFY_DETAILS_CAP:
                    mismatches.append(
                        {
                            "case_no": prev.case_no,
                            "field": field,
                            "snapshot": getattr(prev, field),
                            "intranet": expected[field],
                        }
                    )

    only_in_snapshot = sum(1 for ext_id in existing if ext_id not in merged)

    # 留档:统计 + 差异明细(明细超 500 条截断,防极端情况下报告过大)。
    report = SyncVerificationReport(
        checked=len(merged),
        missing_total=missing_total,
        mismatch_total=mismatch_total,
        only_in_snapshot=only_in_snapshot,
        details={
            "missing_in_snapshot": missing[:_VERIFY_DETAILS_CAP],
            "field_mismatches": mismatches[:_VERIFY_DETAILS_CAP],
            "stage_errors": stage_errors,
        },
    )
    db.add(report)
    logger.info(
        "一致性校验完成:比对 %d 件,缺失 %d,不一致 %d,快照多出 %d,环节失败 %s",
        len(merged), missing_total, mismatch_total, only_in_snapshot, stage_errors or "无",
    )
    return {
        "checked": len(merged),
        "missing_total": missing_total,
        "mismatch_total": mismatch_total,
        "only_in_snapshot": only_in_snapshot,
        "missing_in_snapshot": missing[:_VERIFY_LIST_CAP],
        "field_mismatches": mismatches[:_VERIFY_LIST_CAP],
        "stage_errors": stage_errors,
    }
