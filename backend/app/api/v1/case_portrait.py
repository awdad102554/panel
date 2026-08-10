import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.ai_output import AIOutput
from app.schemas.case import CaseOut
from app.services import case_service

router = APIRouter(prefix="/cases", tags=["case-portrait"])


@router.get("/{case_id}/portrait")
async def get_case_portrait(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user),
) -> dict[str, Any]:
    """案件画像，对应 04 PRD 第五章 / 06 页面原型设计 页面四："30 秒理解案件"。

    汇总案件基本信息 + 各 AI 能力最新一次输出，供前端一屏展示。
    """

    case = await case_service.get_case_workspace(db, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="案件不存在")

    stmt = (
        select(AIOutput)
        .where(AIOutput.case_id == case_id)
        .order_by(AIOutput.created_at.desc())
    )
    result = await db.execute(stmt)
    latest_by_capability: dict[str, AIOutput] = {}
    for output in result.scalars().all():
        latest_by_capability.setdefault(output.capability, output)

    return {
        "case": CaseOut.model_validate(case).model_dump(mode="json"),
        "ai_outputs": {
            capability: {
                "result": output.result,
                "confirmed": output.confirmed_at is not None,
            }
            for capability, output in latest_by_capability.items()
        },
    }
