"""案件记事本服务:subject_key 构造、案件解析(环节)、IP→用户名绑定。

subject_key 是记事归属线程的统一键:
- ext:{external_case_id} —— 内网案件(收件/立案/预约),同一 case_id 跨收件→立案自动衔接;
- virt:{预登记id}        —— 本地预登记案件(独立 SQLite,未落内网)。

记事内容存在 MySQL(与 InfoWeb 共用);案件环节解析仍读 panel 的 PG 快照(ext)或 SQLite(virt)。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.internal_case import InternalCaseTracking, InternalStage
from app.models.user_ip import UserIpBinding
from app.services.internal_case_urgency import (
    ARCHIVED_STEP,
    CLOSED_STEP,
    DECIDING_STEP,
    MEDIATION_STEP,
    PAUSED_STEP,
    is_pre_mediation,
)

SUBJECT_EXT_PREFIX = "ext:"
SUBJECT_VIRT_PREFIX = "virt:"

MAX_PHRASE_LEN = 100


def normalize_phrase(content: str) -> str:
    """校验并规范化快捷内容:去首尾空白;空/超长抛 ValueError(调用方转 422)。"""
    text = (content or "").strip()
    if not text:
        raise ValueError("快捷内容不能为空")
    if len(text) > MAX_PHRASE_LEN:
        raise ValueError(f"快捷内容过长(最多 {MAX_PHRASE_LEN} 字)")
    return text

# 案前调解是「收件」环节的子状态(next_step=3),记事环节单独记为 pre_mediation,
# 前端显示为「收件审查 · 案前调解」,与纯收件(receive)区分。
PRE_MEDIATION_STAGE = "pre_mediation"

# 审理中止:handle 环节 stop=1(is_paused)或 current_step=审理中止,记事环节单独记为 paused,
# 前端显示为「立案在办 · 审理中止」,与普通立案在办(handle)区分。
PAUSED_STAGE = "paused"

# 立案在办(handle)的 current_step → 记事环节细分码,镜像办案进度监控「环节列」的子状态。
# current_step 枚举不封闭,未识别的子状态回落到 handle(立案在办),不报错。
HANDLE_STEP_TO_STAGE: dict[str, str] = {
    PAUSED_STEP: PAUSED_STAGE,          # 审理中止
    MEDIATION_STEP: "mediation",        # 组织调解
    DECIDING_STEP: "deciding",          # 仲裁裁决中
    "待开庭安排": "pending_hearing",     # 待开庭安排
    "待开庭审理": "pending_trial",       # 待开庭审理
    "审理事项进行中": "in_progress",     # 审理事项进行中
    CLOSED_STEP: "closed",              # 已结案
    ARCHIVED_STEP: "archived",          # 已归档
}


def subject_key_for_external(external_case_id: str) -> str:
    """内网案件(收件/立案/预约)的记事线程键。"""
    return f"{SUBJECT_EXT_PREFIX}{external_case_id}"


def subject_key_for_virtual(virtual_case_id: str) -> str:
    """本地预登记案件的记事线程键。"""
    return f"{SUBJECT_VIRT_PREFIX}{virtual_case_id}"


async def resolve_subject_stage(db: AsyncSession, subject_key: str) -> str:
    """解析 subject_key,校验对应案件存在,返回该案件当前环节(stage 字符串)。

    环节用于给新记事打「所在环节」标记:
    - ext:{case_id} → 内网快照当前 stage(reserve/receive/handle),
      其中收件且 next_step=3(案前调解)细化为 "pre_mediation",
      立案在办(handle)按 current_step 细化为 paused/mediation/deciding/pending_hearing/
      pending_trial/in_progress/closed/archived(未识别回落到 handle);
    - virt:{id}    → 固定 "virtual"(预登记,不在主库快照)。
    案件不存在抛 LookupError(调用方转 404);subject_key 非法抛 ValueError(转 400)。
    注意:db 是 panel 的 PG 会话(读快照),不是 MySQL 会话。
    """
    if subject_key.startswith(SUBJECT_EXT_PREFIX):
        external_case_id = subject_key[len(SUBJECT_EXT_PREFIX):]
        if not external_case_id:
            raise ValueError("无效的案件标识")
        row = (
            await db.execute(
                select(InternalCaseTracking).where(
                    InternalCaseTracking.external_case_id == external_case_id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise LookupError("内网案件不存在")
        if is_pre_mediation(row):
            return PRE_MEDIATION_STAGE
        if row.stage == InternalStage.HANDLE:
            if row.current_step:
                mapped = HANDLE_STEP_TO_STAGE.get(row.current_step)
                if mapped:
                    return mapped
            # 兼容旧口径:stop=1 但 current_step 未识别时,仍记为审理中止。
            if row.is_paused:
                return PAUSED_STAGE
        stage = row.stage
        return stage.value if hasattr(stage, "value") else str(stage)

    if subject_key.startswith(SUBJECT_VIRT_PREFIX):
        virtual_case_id = subject_key[len(SUBJECT_VIRT_PREFIX):]
        if not virtual_case_id:
            raise ValueError("无效的案件标识")
        from app.db.virtual import VirtualCase, VirtualSessionLocal

        async with VirtualSessionLocal() as vdb:
            row = await vdb.get(VirtualCase, virtual_case_id)
        if row is None:
            raise LookupError("预登记案件不存在")
        return "virtual"

    raise ValueError("无效的案件标识")


async def get_username_by_ip(mysql_db: AsyncSession, ip: str) -> str | None:
    """按设备 IP 查用户名;未绑定返回 None。mysql_db 是 MySQL 会话。"""
    if not ip:
        return None
    row = (
        await mysql_db.execute(select(UserIpBinding).where(UserIpBinding.ip == ip))
    ).scalar_one_or_none()
    return row.username if row else None


async def bind_username(mysql_db: AsyncSession, ip: str, username: str) -> UserIpBinding:
    """绑定或更新某 IP 的用户名(upsert)。"""
    row = (
        await mysql_db.execute(select(UserIpBinding).where(UserIpBinding.ip == ip))
    ).scalar_one_or_none()
    if row is None:
        row = UserIpBinding(ip=ip, username=username)
        mysql_db.add(row)
    else:
        row.username = username
    await mysql_db.commit()
    await mysql_db.refresh(row)
    return row


# ---------------------------------------------------------------- 记事本总览


async def _resolve_ext_cases(db: AsyncSession, ext_ids: list[str]) -> dict[str, dict]:
    """批量解析内网案件当前信息(案号/当事人/环节)。

    收件转立案有两种形态:
    - 同一 case_id 延续(普通流转):快照里 ext_id 直接就是最新记录;
    - 案前调解立案另建新 case_id:靠 pre_mediation_bindings 映射到 handle 记录,
      未转移成功的旧记事也显示立案后的当前案号。
    快照和绑定都找不到(内网已删除)时不进结果,调用方按"案件已删除"展示。
    """
    out: dict[str, dict] = {}
    if not ext_ids:
        return out

    rows = (
        await db.execute(
            select(InternalCaseTracking).where(
                InternalCaseTracking.external_case_id.in_(ext_ids)
            )
        )
    ).scalars().all()
    for row in rows:
        out[row.external_case_id] = _ext_info(row)

    missing = [i for i in ext_ids if i not in out]
    if missing:
        from app.models.pre_mediation_binding import PreMediationBinding

        bindings = (
            await db.execute(
                select(PreMediationBinding).where(
                    PreMediationBinding.receive_external_case_id.in_(missing)
                )
            )
        ).scalars().all()
        handle_ids = [b.handle_external_case_id for b in bindings]
        handle_rows = {}
        if handle_ids:
            for row in (
                await db.execute(
                    select(InternalCaseTracking).where(
                        InternalCaseTracking.external_case_id.in_(handle_ids)
                    )
                )
            ).scalars().all():
                handle_rows[row.external_case_id] = row
        for b in bindings:
            handle_row = handle_rows.get(b.handle_external_case_id)
            if handle_row is not None:
                out[b.receive_external_case_id] = _ext_info(handle_row)
    return out


def _ext_info(row: InternalCaseTracking) -> dict:
    """快照行 → 总览展示信息(当前案号/当事人/环节)。"""
    payload = row.raw_payload or {}
    stage = row.stage
    stage_code = stage.value if hasattr(stage, "value") else str(stage)
    if is_pre_mediation(row):
        stage_code = PRE_MEDIATION_STAGE
    elif stage_code == InternalStage.HANDLE.value and row.current_step:
        stage_code = HANDLE_STEP_TO_STAGE.get(row.current_step, stage_code)
    return {
        "case_no": row.case_no,
        "applicant": payload.get("applicant") if isinstance(payload.get("applicant"), str) else None,
        "respondent": payload.get("respondent") if isinstance(payload.get("respondent"), str) else None,
        "stage": stage_code,
        "exists": True,
    }


def _virt_info(row) -> dict:
    """预登记案件 → 总览展示信息(收件编号作为案号)。"""
    def _names(parties) -> str | None:
        names = [p.get("name") for p in (parties or []) if isinstance(p, dict) and p.get("name")]
        return "、".join(names) or None

    return {
        "case_no": row.receipt_number,
        "applicant": _names(row.applicants),
        "respondent": _names(row.respondents),
        "stage": "virtual",
        "exists": True,
    }


async def tags_overview(pg_db: AsyncSession, mysql_db: AsyncSession, days: int) -> list[dict]:
    """近 N 天有记事的案件总览,按最近记事时间倒序。

    数据源:MySQL case_tags(记事);案件当前信息从 PG 快照(ext)/
    SQLite(virt)解析——收件转立案后显示当前(立案)案号。
    返回项:{subject_key, case_no, applicant, respondent, stage, tag_count,
    last_content, last_operator, last_at, exists}。
    """
    from app.models.case_tag import CaseTag

    cutoff = datetime.utcnow() - timedelta(days=days)  # case_tags 存 UTC naive
    tags = (
        await mysql_db.execute(
            select(CaseTag)
            .where(CaseTag.created_at >= cutoff)
            .order_by(CaseTag.created_at.asc(), CaseTag.id.asc())
        )
    ).scalars().all()

    # 按线程归并:条数 + 最近一条(时间最大;同刻取 id 大者,与列表排序口径一致)
    grouped: dict[str, dict] = {}
    for tag in tags:
        g = grouped.setdefault(tag.subject_key, {"count": 0, "last": None})
        g["count"] += 1
        g["last"] = tag  # 结果按时间正序,最后一个即最新

    ext_ids = [k[len(SUBJECT_EXT_PREFIX):] for k in grouped if k.startswith(SUBJECT_EXT_PREFIX)]
    virt_ids = [k[len(SUBJECT_VIRT_PREFIX):] for k in grouped if k.startswith(SUBJECT_VIRT_PREFIX)]
    ext_info = await _resolve_ext_cases(pg_db, ext_ids)

    virt_info: dict[str, dict] = {}
    if virt_ids:
        from app.db.virtual import VirtualCase, VirtualSessionLocal

        async with VirtualSessionLocal() as vdb:
            for row in (
                await vdb.execute(select(VirtualCase).where(VirtualCase.id.in_(virt_ids)))
            ).scalars().all():
                virt_info[row.id] = _virt_info(row)

    items: list[dict] = []
    for subject_key, g in grouped.items():
        last = g["last"]
        if subject_key.startswith(SUBJECT_EXT_PREFIX):
            info = ext_info.get(subject_key[len(SUBJECT_EXT_PREFIX):])
        else:
            info = virt_info.get(subject_key[len(SUBJECT_VIRT_PREFIX):])
        if info is None:
            info = {
                "case_no": None,
                "applicant": None,
                "respondent": None,
                "stage": "",
                "exists": False,  # 快照/预登记里已不存在(内网删除或未同步)
            }
        items.append(
            {
                "subject_key": subject_key,
                "case_no": info["case_no"],
                "applicant": info["applicant"],
                "respondent": info["respondent"],
                "stage": info["stage"],
                "tag_count": g["count"],
                "last_content": last.content,
                "last_operator": last.operator,
                "last_at": last.created_at.strftime("%Y-%m-%dT%H:%M:%S") + "Z",
                "exists": info["exists"],
            }
        )
    items.sort(key=lambda x: x["last_at"], reverse=True)
    return items


async def count_tagged_cases(mysql_db: AsyncSession, days: int) -> int:
    """近 N 天有记事的案件数(总览卡片计数;失败时调用方按 0 处理)。"""
    from sqlalchemy import func

    from app.models.case_tag import CaseTag

    cutoff = datetime.utcnow() - timedelta(days=days)
    return int(
        (
            await mysql_db.execute(
                select(func.count(func.distinct(CaseTag.subject_key))).where(
                    CaseTag.created_at >= cutoff
                )
            )
        ).scalar_one()
    )
