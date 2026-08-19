import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Action, require_permission
from app.db.session import get_db
from app.models.ai_model import AIModelConfig
from app.repositories import ai_model_repository as repo
from app.schemas.ai_model import AIModelCreate, AIModelOut, AIModelUpdate

router = APIRouter(prefix="/ai-models", tags=["ai-models"])


def _mask_key(api_key: str) -> str:
    """脱敏：保留前缀与后 4 位，中间以 **** 代替。"""

    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "****"
    return f"{api_key[:3]}****{api_key[-4:]}"


def _to_out(model: AIModelConfig) -> AIModelOut:
    return AIModelOut(
        id=model.id,
        name=model.name,
        provider=model.provider,
        base_url=model.base_url,
        api_key_masked=_mask_key(model.api_key),
        model_name=model.model_name,
        temperature=model.temperature,
        max_tokens=model.max_tokens,
        supports_vision=model.supports_vision,
        is_enabled=model.is_enabled,
        remark=model.remark,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


@router.get("", response_model=list[AIModelOut])
async def list_ai_models(
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_permission(Action.MODEL_MANAGE)),
) -> list[AIModelOut]:
    models = await repo.list_models(db)
    return [_to_out(m) for m in models]


@router.get("/active", response_model=AIModelOut | None)
async def get_active_ai_model(
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_permission(Action.MODEL_MANAGE)),
) -> AIModelOut | None:
    model = await repo.get_enabled_model(db)
    return _to_out(model) if model else None


@router.post("", response_model=AIModelOut, status_code=status.HTTP_201_CREATED)
async def create_ai_model(
    payload: AIModelCreate,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_permission(Action.MODEL_MANAGE)),
) -> AIModelOut:
    model = await repo.create_model(db, payload.model_dump())
    await db.commit()
    await db.refresh(model)
    return _to_out(model)


@router.put("/{model_id}", response_model=AIModelOut)
async def update_ai_model(
    model_id: uuid.UUID,
    payload: AIModelUpdate,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_permission(Action.MODEL_MANAGE)),
) -> AIModelOut:
    model = await repo.get_model(db, model_id)
    if model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型配置不存在")
    # exclude_unset：未提供的字段不动；api_key 为空视为不改密钥
    data = payload.model_dump(exclude_unset=True)
    if not data.get("api_key"):
        data.pop("api_key", None)
    model = await repo.update_model(db, model, data)
    await db.commit()
    await db.refresh(model)
    return _to_out(model)


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ai_model(
    model_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_permission(Action.MODEL_MANAGE)),
) -> None:
    model = await repo.get_model(db, model_id)
    if model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型配置不存在")
    await repo.delete_model(db, model)
    await db.commit()


@router.post("/{model_id}/enable", response_model=AIModelOut)
async def enable_ai_model(
    model_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_permission(Action.MODEL_MANAGE)),
) -> AIModelOut:
    model = await repo.get_model(db, model_id)
    if model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型配置不存在")
    await repo.set_enabled(db, model_id)
    await db.commit()
    await db.refresh(model)
    return _to_out(model)
