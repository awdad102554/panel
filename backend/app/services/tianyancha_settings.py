"""天眼查 API Key 的 DB 覆盖存取(复用 system_settings 表,见 time_limits.py)。

key 优先级:system_settings 里的 tianyancha_api_key(天眼查页 UI 保存)> backend/.env 的
TIANYANCHA_API_KEY > 未配置。这样用户可在"天眼查"页直接配 key,无需改 .env 或重启。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.system_setting import SystemSetting

SETTING_KEY = "tianyancha_api_key"
MAX_KEY_LEN = 128  # 与 system_settings.value String(128) 对齐


def clean_api_key(api_key: str | None) -> str:
    """去空白并校验长度;返回合法 key,超长抛 ValueError。"""
    key = (api_key or "").strip()
    if len(key) > MAX_KEY_LEN:
        raise ValueError(f"API Key 过长(最多 {MAX_KEY_LEN} 字符)")
    return key


def mask_api_key(key: str) -> str:
    """脱敏展示:只留尾部 4 位,长度 ≤4 则全掩。"""
    if not key:
        return ""
    return f"••••{key[-4:]}" if len(key) > 4 else "••••"


async def describe_tianyancha_config(db: AsyncSession) -> dict:
    """当前天眼查配置:{configured, api_key_masked, source, key}。"""
    row = (
        await db.execute(select(SystemSetting).where(SystemSetting.key == SETTING_KEY))
    ).scalar_one_or_none()
    db_key = row.value.strip() if (row is not None and row.value.strip()) else ""
    env_key = get_settings().tianyancha_api_key
    key = db_key or env_key
    source = "db" if db_key else ("env" if env_key else None)
    return {
        "configured": bool(key),
        "api_key_masked": mask_api_key(key),
        "source": source,
        "key": key,
    }


async def get_tianyancha_api_key(db: AsyncSession) -> str:
    """当前生效的 API Key(DB 覆盖优先,否则回落 .env)。"""
    return (await describe_tianyancha_config(db))["key"]


async def save_tianyancha_api_key(db: AsyncSession, api_key: str | None) -> None:
    """保存 API Key(空值=清除 DB 覆盖、回落 .env);由调用方 commit。"""
    key = clean_api_key(api_key)
    row = (
        await db.execute(select(SystemSetting).where(SystemSetting.key == SETTING_KEY))
    ).scalar_one_or_none()
    if key:
        if row is None:
            db.add(SystemSetting(key=SETTING_KEY, value=key))
        else:
            row.value = key
    elif row is not None:
        await db.delete(row)
