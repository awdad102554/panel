"""案件记事本服务:subject_key 构造、案件解析(环节)、IP→用户名绑定。

subject_key 是记事归属线程的统一键:
- ext:{external_case_id} —— 内网案件(收件/立案/预约),同一 case_id 跨收件→立案自动衔接;
- virt:{预登记id}        —— 本地预登记案件(独立 SQLite,未落内网)。

记事内容存在 MySQL(与 InfoWeb 共用);案件环节解析仍读 panel 的 PG 快照(ext)或 SQLite(virt)。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.internal_case import InternalCaseTracking
from app.models.user_ip import UserIpBinding

SUBJECT_EXT_PREFIX = "ext:"
SUBJECT_VIRT_PREFIX = "virt:"


def subject_key_for_external(external_case_id: str) -> str:
    """内网案件(收件/立案/预约)的记事线程键。"""
    return f"{SUBJECT_EXT_PREFIX}{external_case_id}"


def subject_key_for_virtual(virtual_case_id: str) -> str:
    """本地预登记案件的记事线程键。"""
    return f"{SUBJECT_VIRT_PREFIX}{virtual_case_id}"


async def resolve_subject_stage(db: AsyncSession, subject_key: str) -> str:
    """解析 subject_key,校验对应案件存在,返回该案件当前环节(stage 字符串)。

    环节用于给新记事打「所在环节」标记:
    - ext:{case_id} → 内网快照当前 stage(reserve/receive/handle);
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
