from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置，值来自环境变量或 backend/.env（见 .env.example）。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "智能办案平台"
    api_prefix: str = "/api/v1"

    database_url: str = "postgresql+asyncpg://panel:panel@localhost:5432/panel"

    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 12

    cors_origins: list[str] = ["http://localhost:5173"]

    # 内网案件系统(10.96.10.78:8080)——数据源与 InfoWeb 同一套账号/登录流程。
    # 默认值取 InfoWeb modules/config.py 现用值,可被 backend/.env 覆盖。
    case_system_enabled: bool = True
    case_system_base_url: str = "http://10.96.10.78:8080"
    case_system_username: str = "huhailiang"
    case_system_password: str = (
        "eyJpdiI6IjFDalU2azNBY1UrVkhUazBad0ZpY3c9PSIsInZhbHVlIjoiNE16d1NHXC9ISkV0"
        "Z1ZnalFNSUZldU9hUDMwYTNNaGxhMldRU09Ic0FkeFU9IiwibWFjIjoiM2MyZjVhYWRkNjli"
        "NThhMjc4YjE2MThiMmU1NmNjMzIxYjAyMTkxM2IzZjVjN2MyNjFlNzliYTQ1NjQ5MTM3ZSJ9"
    )
    case_system_timeout: int = 30
    case_system_session_hours: int = 10

    # 审限占位值(天):真实业务规则待用户后续明确,当前用户已确认"先用占位符/随意设置"。
    # 用于案件未手动填写 statute_deadline 时,从 filed_date 起算的默认审限天数。
    # TODO: 替换为正式的审限业务规则后删除此占位注释。
    case_statute_period_days: int = 120

    # 内网案件监控——同步与时效阈值配置(已按工作人员确认口径设置,可通过 .env 覆盖)。
    case_sync_interval_minutes: int = 60  # 后台定时同步间隔(分钟)
    case_urgency_reserve_days: int = 3  # 线上预约阶段时限(只定超期点;警告起点用统一的临近/紧急阈值)
    case_urgency_receive_days: int = 5  # 收件审查阶段:时限 5 天(自然日;以内网原生 receive_time_limit 为准)
    case_urgency_soon_days: int = 3  # handle 阶段:剩余审理天数≤多少天算"临近"
    case_urgency_urgent_days: int = 1  # handle 阶段:剩余审理天数≤多少天升级"紧急"(需小于临近阈值)
    case_urgency_paused_alert_days: int = 15  # 审理中止:暂停超过多少天需要提醒(标"中止XX天")
    case_mediation_alert_days: int = 30  # 组织调解:进入调解环节超过多少天需提醒(约一个月)

    # 预登记案件警告阈值(按登记后的自然日数):超过临近阈值标"临近",超过紧急阈值标"紧急"。
    virtual_case_soon_days: int = 30  # 预登记临近阈值(天)
    virtual_case_urgent_days: int = 60  # 预登记紧急阈值(天,需大于临近阈值)


@lru_cache
def get_settings() -> Settings:
    return Settings()
