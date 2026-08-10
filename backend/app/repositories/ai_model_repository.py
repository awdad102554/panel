import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_model import AIModelConfig


async def list_models(db: AsyncSession) -> list[AIModelConfig]:
    stmt = select(AIModelConfig).order_by(AIModelConfig.updated_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_model(db: AsyncSession, model_id: uuid.UUID) -> AIModelConfig | None:
    return await db.get(AIModelConfig, model_id)


async def get_enabled_model(db: AsyncSession) -> AIModelConfig | None:
    stmt = select(AIModelConfig).where(AIModelConfig.is_enabled.is_(True)).limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_model(db: AsyncSession, data: dict) -> AIModelConfig:
    model = AIModelConfig(**data)
    db.add(model)
    await db.flush()
    return model


async def update_model(db: AsyncSession, model: AIModelConfig, data: dict) -> AIModelConfig:
    for key, value in data.items():
        setattr(model, key, value)
    await db.flush()
    return model


async def delete_model(db: AsyncSession, model: AIModelConfig) -> None:
    await db.delete(model)
    await db.flush()


async def set_enabled(db: AsyncSession, model_id: uuid.UUID) -> None:
    """保证全局唯一启用：先全部置 False，再把目标置 True。"""

    await db.execute(update(AIModelConfig).values(is_enabled=False))
    await db.execute(
        update(AIModelConfig).where(AIModelConfig.id == model_id).values(is_enabled=True)
    )
    await db.flush()
