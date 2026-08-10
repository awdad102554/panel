"""时限设置路由:读取/保存用户可调的阈值,见 services/time_limits.py。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.services.time_limits import (
    TIME_LIMIT_SPECS,
    get_time_limits,
    reset_time_limits,
    save_time_limits,
)

router = APIRouter(prefix="/settings", tags=["settings"])


class TimeLimitItem(BaseModel):
    key: str
    label: str
    value: int
    default: int
    description: str
    minimum: int
    maximum: int


class TimeLimitsOut(BaseModel):
    items: list[TimeLimitItem]


class TimeLimitsUpdate(BaseModel):
    values: dict[str, int]


@router.get("/time-limits", response_model=TimeLimitsOut)
async def read_time_limits(
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user),
) -> TimeLimitsOut:
    values = await get_time_limits(db)
    return TimeLimitsOut(
        items=[
            TimeLimitItem(
                key=key,
                label=spec.label,
                value=values[key],
                default=spec.default,
                description=spec.description,
                minimum=spec.minimum,
                maximum=spec.maximum,
            )
            for key, spec in TIME_LIMIT_SPECS.items()
        ]
    )


@router.put("/time-limits", response_model=TimeLimitsOut)
async def update_time_limits(
    payload: TimeLimitsUpdate,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user),
) -> TimeLimitsOut:
    try:
        await save_time_limits(db, payload.values)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await db.commit()
    return await read_time_limits(db=db, _current_user=_current_user)


@router.post("/time-limits/reset", response_model=TimeLimitsOut)
async def reset_time_limits_endpoint(
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user),
) -> TimeLimitsOut:
    await reset_time_limits(db)
    await db.commit()
    return await read_time_limits(db=db, _current_user=_current_user)
