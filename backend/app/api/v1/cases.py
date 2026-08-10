import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.permissions import Action, require_permission
from app.db.session import get_db
from app.models.case import CaseStatus
from app.schemas.case import CaseCreate, CaseOut, CaseTransitionRequest
from app.services import case_service
from app.services.case_lifecycle import InvalidTransitionError, transition_case_status

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("", response_model=list[CaseOut])
async def list_cases(
    status_filter: CaseStatus | None = None,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user),
) -> list[CaseOut]:
    """案件池，对应 04 PRD 模块二。"""

    cases = await case_service.get_case_pool(db, status=status_filter)
    return [CaseOut.model_validate(c) for c in cases]


@router.post("", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
async def create_case(
    payload: CaseCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission(Action.EDIT)),
) -> CaseOut:
    case = await case_service.create_case(db, claims=payload.claims, operator=current_user.display_name)
    await db.commit()
    return CaseOut.model_validate(case)


@router.get("/{case_id}", response_model=CaseOut)
async def get_case_workspace(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user),
) -> CaseOut:
    """案件工作台唯一入口，对应 04 PRD 模块三。"""

    case = await case_service.get_case_workspace(db, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="案件不存在")
    return CaseOut.model_validate(case)


@router.post("/{case_id}/transition", response_model=CaseOut)
async def transition_case(
    case_id: uuid.UUID,
    payload: CaseTransitionRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission(Action.EDIT)),
) -> CaseOut:
    case = await case_service.get_case_workspace(db, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="案件不存在")

    try:
        case = await transition_case_status(
            db, case, payload.target_status, operator=current_user.display_name
        )
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await db.commit()
    return CaseOut.model_validate(case)
