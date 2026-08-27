import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class AIModelConfig(Base):
    """AI 模型接入配置，对应"模型管理"页面。

    支持配置多套模型（供应商 / Base URL / API Key / 模型名），同一时刻仅一个
    `is_enabled=True` 生效（由 repository.set_enabled 保证）。当前阶段真实 HTTP
    调用仍留占位，AI 能力回退 mock 输出；本表提供配置的持久化与管理入口。
    """

    __tablename__ = "ai_model_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(32))  # openai/qwen/deepseek/azure_openai/custom
    base_url: Mapped[str] = mapped_column(String(255))
    api_key: Mapped[str] = mapped_column(String(255))  # 明文存储，响应脱敏；骨架阶段合理简化
    model_name: Mapped[str] = mapped_column(String(64))
    temperature: Mapped[float | None] = mapped_column(Float, default=0.2, nullable=True)
    # 单次请求最大输出 token 数;新增配置时前端按主流模型上限预设自动填入(可手改),
    # 供真实 LLM Provider 发请求时使用(mock 阶段不落请求)。
    max_tokens: Mapped[int | None] = mapped_column(Integer, default=8192, nullable=True)
    # 是否支持图片输入(视觉模型):预约审查时是否把证件照片发给模型看图核对。
    supports_vision: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
