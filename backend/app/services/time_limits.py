"""时限设置:阈值存数据库,用户可在"时限设置"页自行调整,实时生效。

存储是简单的 key-value 表(system_settings);读取带 30 秒进程内缓存,
避免每次聚合都查库。未设置的项回落到 TIME_LIMIT_SPECS 里的默认值
(与调整前 config.py 的口径一致)。

compute_urgency 仍接收 Settings 对象:调用方用 effective_settings() 把库里的
值覆盖进 Settings 副本。法定审限(45 天)等业务规则时限为固定值,不走这里。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.system_setting import SystemSetting


@dataclass(frozen=True)
class TimeLimitSpec:
    label: str
    default: int
    description: str
    minimum: int = 1
    maximum: int = 365


# 可调的时限项,只含"提醒/警告阈值"——法定与业务时限(审限 45 天、收件审查 5 天、
# 预约 3 天)由内网和业务规则定死,不开放设置(2026-07-31 工作人员确认)。
# key 即 system_settings.key,与 Settings 同名字段由 effective_settings 按名覆盖。
TIME_LIMIT_SPECS: dict[str, TimeLimitSpec] = {
    "case_urgency_soon_days": TimeLimitSpec(
        "时效临近阈值", 3, "在办案件剩余审理天数 ≤ 此值时标为\"临近\",进入待办案件", 1, 60
    ),
    "case_urgency_urgent_days": TimeLimitSpec(
        "时效紧急阈值", 1, "在办案件剩余审理天数 ≤ 此值时升级为\"紧急\"(橙红色,排在临近之前;需小于临近阈值)", 1, 59
    ),
    "case_urgency_paused_alert_days": TimeLimitSpec(
        "中止过久阈值", 15, "审理中止超过此天数升级为\"中止过久\",单独卡片提醒", 1, 180
    ),
    "case_mediation_alert_days": TimeLimitSpec(
        "调解超时提醒", 30, "组织调解超过此天数提醒关注", 1, 180
    ),
    "pre_mediation_soon_days": TimeLimitSpec(
        "案前调解临近阈值", 30, "案前调解进入调解满此天数标为\"临近\",总览卡片右上角提醒", 1, 365
    ),
    "pre_mediation_urgent_days": TimeLimitSpec(
        "案前调解紧急阈值", 45, "案前调解进入调解满此天数升级为\"紧急\"(需大于临近阈值)", 2, 365
    ),
    "case_sync_interval_minutes": TimeLimitSpec(
        "内网同步间隔", 60, "后台轻量同步的间隔(分钟),下轮同步时生效", 5, 1440
    ),
    "virtual_case_soon_days": TimeLimitSpec(
        "预登记临近阈值", 30, "预登记案件登记超过此天数未录入内网标为\"临近\"", 1, 365
    ),
    "virtual_case_urgent_days": TimeLimitSpec(
        "预登记紧急阈值", 60, "预登记案件登记超过此天数未录入内网升级为\"紧急\"(需大于预登记临近阈值)", 2, 365
    ),
    "tag_overview_days": TimeLimitSpec(
        "记事本总览天数", 30, "总览\"记事本\"卡片及点开后默认统计近多少天内有记事的案件", 1, 365
    ),
}

_cache: tuple[float, dict[str, int]] | None = None
_CACHE_TTL_SECONDS = 30


async def get_time_limits(db: AsyncSession) -> dict[str, int]:
    """当前生效的全部时限值(库覆盖 + 默认回落),带 30 秒缓存。"""
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_TTL_SECONDS:
        return _cache[1]

    rows = (await db.execute(select(SystemSetting))).scalars().all()
    stored = {row.key: row.value for row in rows}
    values: dict[str, int] = {}
    for key, spec in TIME_LIMIT_SPECS.items():
        raw = stored.get(key)
        try:
            values[key] = int(raw) if raw is not None else spec.default
        except (TypeError, ValueError):
            values[key] = spec.default
    _cache = (now, values)
    return values


def _validate(updates: dict[str, int]) -> dict[str, int]:
    """校验并返回合法子集;不认识的 key 忽略,越界/非正数报 ValueError。"""
    cleaned: dict[str, int] = {}
    for key, value in updates.items():
        spec = TIME_LIMIT_SPECS.get(key)
        if spec is None:
            continue
        # bool 是 int 子类,显式排除,防止 True 被当成 1 存进去。
        if isinstance(value, bool) or not isinstance(value, int) or not (spec.minimum <= value <= spec.maximum):
            raise ValueError(f"{spec.label} 需在 {spec.minimum}~{spec.maximum} 之间")
        cleaned[key] = value
    return cleaned


async def save_time_limits(db: AsyncSession, updates: dict[str, int]) -> None:
    """保存时限设置(部分更新),由调用方 commit 后再读取生效值。

    只失效缓存、不预填:避免 commit 失败时缓存里残留未落库的值。
    """
    global _cache
    cleaned = _validate(updates)
    existing = {
        row.key: row
        for row in (await db.execute(select(SystemSetting))).scalars().all()
    }
    # 先合并出保存后的生效值再校验,通过才落库。
    merged_raw = {k: r.value for k, r in existing.items()}
    merged_raw.update({k: str(v) for k, v in cleaned.items()})
    merged = {key: int(merged_raw.get(key, spec.default)) for key, spec in TIME_LIMIT_SPECS.items()}
    if merged["case_urgency_urgent_days"] >= merged["case_urgency_soon_days"]:
        raise ValueError("时效紧急阈值需小于临近阈值")
    if merged["virtual_case_urgent_days"] <= merged["virtual_case_soon_days"]:
        raise ValueError("预登记紧急阈值需大于临近阈值")
    if merged["pre_mediation_urgent_days"] <= merged["pre_mediation_soon_days"]:
        raise ValueError("案前调解紧急阈值需大于临近阈值")
    for key, value in cleaned.items():
        if key in existing:
            existing[key].value = str(value)
        else:
            db.add(SystemSetting(key=key, value=str(value)))
    _cache = None


async def reset_time_limits(db: AsyncSession) -> None:
    """全部恢复默认(清空库里的覆盖),由调用方 commit 后再读取。"""
    global _cache
    for row in (await db.execute(select(SystemSetting))).scalars().all():
        await db.delete(row)
    _cache = None


async def effective_settings(db: AsyncSession) -> Settings:
    """Settings 副本:把库里的提醒阈值覆盖到 case_urgency_* 同名字段上。

    case_sync_interval_minutes 是调度参数(同步循环单独读库),不覆盖进副本,
    避免与 main.py 的读取路径分叉。
    """
    values = await get_time_limits(db)
    override = {
        key: value
        for key, value in values.items()
        if key != "case_sync_interval_minutes" and key in Settings.model_fields
    }
    return get_settings().model_copy(update=override)
