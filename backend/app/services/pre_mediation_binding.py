"""案前调解 → 立案 一对一绑定与记事转移。

背景:内网立案时同一纠纷另建 handle 记录(新 case_id),原收件(receive)记录停在
next_step=3(案前调解)永不关闭,且两者之间没有直接外键(旧 case_id/source_id 均为 0)。
可靠关联键是 申请人身份证号(applicant_arr[].id_number,18 位)+ 被申请人名称 +
时间窗口(handle_at 日期 ≥ review_at 日期)。绑定后:
- 该案前调解从总览"案前调解"卡片、监控列表、InfoWeb 提醒里消失(进入下一阶段);
- 记事 case_tags.subject_key 从 ext:{receive_id} 转挂到 ext:{handle_id}。

绑定在同步时自动执行(见 internal_case_sync._sync_internal_cases)。轻量同步的 merged
只含在办/今日立案的 handle,历史已结案立案案件靠 search 按申请人姓名兜底补拉一次;
绑定一经落库即持久,后续轮次跳过,故兜底请求只在首次回填时发生。
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.case_system.client import CaseSystemClient, CaseSystemError
from app.models.internal_case import InternalStage
from app.models.pre_mediation_binding import PreMediationBinding
from app.services.internal_case_urgency import PRE_MEDIATION_NEXT_STEP

logger = logging.getLogger(__name__)

_HANDLE_PATH = "/v1/api/admin/arb/handle"

# 内网时间戳是无时区本地时间(CST),解析后无需再换算时区(与 internal_case_sync 一致)。
_INTRANET_TZ = timezone(timedelta(hours=8))


def _parse_dt(value) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=_INTRANET_TZ)
        except ValueError:
            continue
    return None


def _coerce_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None


def _applicant_id_numbers(payload: dict) -> list[str]:
    """申请人身份证号/统一社会信用代码列表(保序,去重)。"""
    out: list[str] = []
    for a in payload.get("applicant_arr") or []:
        if isinstance(a, dict):
            idn = (a.get("id_number") or "").strip()
            if idn and idn not in out:
                out.append(idn)
    return out


def _respondent_names(payload: dict) -> set[str]:
    """被申请人名称集合(含顶层 respondent 兜底)。"""
    out: set[str] = set()
    for r in payload.get("respondent_arr") or []:
        if isinstance(r, dict):
            name = (r.get("name") or "").strip()
            if name:
                out.add(name)
    top = payload.get("respondent")
    if isinstance(top, str) and top.strip():
        out.add(top.strip())
    return out


def _entry_date(payload: dict) -> date | None:
    """案前调解进入时间锚点日期(review_at 优先,回落 receive_at/created_at)。"""
    for key in ("review_at", "receive_at", "created_at"):
        dt = _parse_dt(payload.get(key))
        if dt is not None:
            return dt.date()
    return None


def _handle_date(payload: dict) -> date | None:
    """立案日期(handle_at)。"""
    dt = _parse_dt(payload.get("handle_at"))
    return dt.date() if dt is not None else None


def _is_pre_mediation_record(mapped: dict) -> bool:
    """同步合并结果里的案前调解收件记录(receive + next_step=3)。"""
    if mapped["stage"] != InternalStage.RECEIVE:
        return False
    return _coerce_int((mapped["raw_payload"] or {}).get("next_step")) == PRE_MEDIATION_NEXT_STEP


def _index_handles(handle_rows: list[tuple[str, str | None, dict]]) -> dict[str, list[tuple[str, str | None, dict]]]:
    """按申请人身份证号索引立案记录 → id_number → [(handle_id, case_no, payload)]。"""
    index: dict[str, list[tuple[str, str | None, dict]]] = defaultdict(list)
    for handle_id, case_no, payload in handle_rows:
        for idn in _applicant_id_numbers(payload):
            index[idn].append((handle_id, case_no, payload))
    return index


def _find_handle_match(
    payload: dict,
    handle_index: dict[str, list[tuple[str, str | None, dict]]],
) -> tuple[str, str | None] | None:
    """在立案候选里找案前调解的对应案件。

    匹配条件(全部满足,取立案日期最近的一个以消歧"一人两案"):
    - 申请人身份证号有交集;
    - 被申请人名称有交集;
    - 立案日期 ≥ 案前调解进入日期(防止串到更早的旧案)。
    """
    receive_ids = _applicant_id_numbers(payload)
    if not receive_ids:
        return None
    respondents = _respondent_names(payload)
    entry = _entry_date(payload)
    best: tuple[tuple[date, str], tuple[str, str | None]] | None = None
    for idn in receive_ids:
        for handle_id, case_no, hpayload in handle_index.get(idn, []):
            if respondents and not (respondents & _respondent_names(hpayload)):
                continue
            hdate = _handle_date(hpayload)
            if hdate is None:
                continue
            if entry is not None and hdate < entry:
                continue
            key = (hdate, handle_id)
            if best is None or key < best[0]:
                best = (key, (handle_id, case_no))
    return best[1] if best else None


async def _search_handle_by_applicant(client: CaseSystemClient, payload: dict) -> list[dict]:
    """兜底:按申请人姓名搜 handle 接口,返回候选记录(供本地精确匹配)。

    内网 handle 的 search 按申请人姓名命中(不按身份证号,实测 search=身份证号返回空)。
    取第一个申请人姓名搜索;多人案件首申请人通常能命中。失败/为空返回 []。
    """
    name: str | None = None
    for a in payload.get("applicant_arr") or []:
        if isinstance(a, dict) and (a.get("name") or "").strip():
            name = (a.get("name") or "").strip()
            break
    if not name:
        top = payload.get("applicant")
        if isinstance(top, str) and top.strip():
            name = top.strip()
    if not name:
        return []
    try:
        resp = await client.get(
            _HANDLE_PATH, params={"page": 1, "page_size": 50, "search": name}
        )
    except CaseSystemError as exc:
        logger.warning("案前调解绑定按申请人姓名搜索 handle 失败: %s", exc)
        return []
    if resp.status_code != 200:
        logger.warning("案前调解绑定搜索 handle 非 200: %s", resp.status_code)
        return []
    try:
        body = resp.json()
    except ValueError:
        return []
    data = body.get("data") if isinstance(body, dict) else None
    batch = (data.get("data") or data.get("list") or []) if isinstance(data, dict) else []
    return [b for b in batch if isinstance(b, dict)]


async def _transfer_tags(receive_id: str, handle_id: str) -> None:
    """记事转挂:ext:{receive_id} → ext:{handle_id}(只改 subject_key,不改成片时间/环节)。"""
    from app.db.mysql import MysqlSessionLocal
    from app.models.case_tag import CaseTag

    old = f"ext:{receive_id}"
    new = f"ext:{handle_id}"
    async with MysqlSessionLocal() as mdb:
        await mdb.execute(
            update(CaseTag).where(CaseTag.subject_key == old).values(subject_key=new)
        )
        await mdb.commit()


async def load_bound_receive_ids(db: AsyncSession) -> set[str]:
    """已绑定的案前调解收件 case_id 集合(供总览/监控/提醒过滤)。"""
    rows = (await db.execute(select(PreMediationBinding.receive_external_case_id))).scalars().all()
    return set(rows)


async def auto_bind_pre_mediation(
    db: AsyncSession, client: CaseSystemClient, merged: dict[str, dict]
) -> int:
    """同步合并结果里自动绑定案前调解 → 立案,并转移记事。返回本轮新建绑定数。

    全程不 commit:绑定行由调用方(sync)随快照一起提交;记事转移单独在 MySQL 提交。
    """
    existing = {
        b.receive_external_case_id: b
        for b in (await db.execute(select(PreMediationBinding))).scalars().all()
    }

    pre_mediation: list[tuple[str, dict]] = []
    handle_rows: list[tuple[str, str | None, dict]] = []
    for ext_id, mapped in merged.items():
        if _is_pre_mediation_record(mapped):
            pre_mediation.append((ext_id, mapped["raw_payload"] or {}))
        elif mapped["stage"] == InternalStage.HANDLE:
            handle_rows.append((ext_id, mapped.get("case_no"), mapped["raw_payload"] or {}))

    if not pre_mediation:
        return 0

    handle_index = _index_handles(handle_rows)
    bound = 0
    for receive_id, payload in pre_mediation:
        if receive_id in existing:
            continue
        match = _find_handle_match(payload, handle_index)
        if match is None:
            searched = await _search_handle_by_applicant(client, payload)
            if searched:
                searched_rows = [
                    (str(b.get("case_id")), b.get("case_no"), b)
                    for b in searched
                    if b.get("case_id") is not None
                ]
                match = _find_handle_match(payload, _index_handles(searched_rows))
        if match is None:
            continue
        handle_id, handle_case_no = match
        # 先转记事(MySQL 独立提交),再落绑定(PG 随同步提交)。若记事转移失败则不落绑定、
        # 下轮重试——避免出现"已绑定但记事未转"的半截状态(2026-08-24 审查发现)。
        try:
            await _transfer_tags(receive_id, handle_id)
        except Exception as exc:
            logger.warning(
                "案前调解绑定记事转移失败(收件 %s → 立案 %s),跳过本轮: %s",
                receive_id, handle_id, exc,
            )
            continue
        db.add(
            PreMediationBinding(
                receive_external_case_id=receive_id,
                handle_external_case_id=handle_id,
                handle_case_no=handle_case_no,
            )
        )
        existing[receive_id] = None  # 标记本轮已绑,避免重复
        bound += 1
        logger.info("案前调解绑定:收件 %s → 立案 %s(%s)", receive_id, handle_id, handle_case_no or "-")

    return bound
