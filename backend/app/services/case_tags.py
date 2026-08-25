"""案件记事本服务:subject_key 构造、案件解析(环节)、IP→用户名绑定。

subject_key 是记事归属线程的统一键:
- ext:{external_case_id} —— 内网案件(收件/立案/预约),同一 case_id 跨收件→立案自动衔接;
- virt:{预登记id}        —— 本地预登记案件(独立 SQLite,未落内网)。

记事内容存在 MySQL(与 InfoWeb 共用);案件环节解析仍读 panel 的 PG 快照(ext)或 SQLite(virt)。
"""

from __future__ import annotations

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
