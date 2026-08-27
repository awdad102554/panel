import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.permissions import Action, require_permission
from app.db.session import get_db
from app.models.ai_output import AICapabilityType, AIOutput
from app.schemas.ai import AIInvokeRequest, AIOutputOut
from app.services import case_service
from app.services.timeline_service import add_timeline_event

router = APIRouter(prefix="/cases", tags=["ai"])

_CAPABILITY_REGISTRY = {}


def _load_registry():
    """延迟导入各 Capability，避免模块加载顺序问题。"""

    if not _CAPABILITY_REGISTRY:
        from app.ai.case_understanding import CaseUnderstandingCapability
        from app.ai.decision_draft import DecisionDraftCapability
        from app.ai.intake_review import IntakeReviewCapability
        from app.ai.legal_analysis import LegalAnalysisCapability

        _CAPABILITY_REGISTRY.update(
            {
                AICapabilityType.INTAKE_REVIEW: IntakeReviewCapability(),
                AICapabilityType.CASE_UNDERSTANDING: CaseUnderstandingCapability(),
                AICapabilityType.LEGAL_ANALYSIS: LegalAnalysisCapability(),
                AICapabilityType.DECISION_DRAFT: DecisionDraftCapability(),
            }
        )
    return _CAPABILITY_REGISTRY


def _case_to_context(case) -> dict:
    return {
        "case_no": case.case_no,
        "status": case.status.value if hasattr(case.status, "value") else case.status,
        "claims": case.claims,
        "parties": [
            {"party_type": p.party_type.value, "name": p.name} for p in case.parties
        ],
    }


@router.post("/{case_id}/ai/invoke", response_model=AIOutputOut)
async def invoke_ai_capability(
    case_id: uuid.UUID,
    payload: AIInvokeRequest,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_permission(Action.AI_INVOKE)),
) -> AIOutputOut:
    """AI 能力中心统一入口，对应 07 技术沟通说明"六、AI 调用原则"：

    读取案件数据 -> 调用 AI -> 返回结构化结果 -> 落库等待人工确认，
    本接口不直接写回业务字段。
    """

    case = await case_service.get_case_workspace(db, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="案件不存在")

    capability = _load_registry().get(payload.capability)
    if capability is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未知 AI 能力")

    ai_result = await capability.run(_case_to_context(case))

    from app.repositories import ai_model_repository

    enabled_model = await ai_model_repository.get_enabled_model(db)
    model_note = (
        f"（模型：{enabled_model.model_name}）"
        if enabled_model is not None
        else "（未配置模型，使用 mock）"
    )

    ai_output = AIOutput(case_id=case_id, capability=payload.capability, result=ai_result.model_dump())
    db.add(ai_output)
    await add_timeline_event(
        db,
        case_id=case_id,
        event_type="ai_output",
        summary=f"AI（{payload.capability.value}）{model_note}生成建议：{ai_result.summary}",
    )
    await db.commit()
    await db.refresh(ai_output)
    return AIOutputOut.model_validate(ai_output)


@router.post("/{case_id}/ai/{ai_output_id}/confirm", response_model=AIOutputOut)
async def confirm_ai_output(
    case_id: uuid.UUID,
    ai_output_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission(Action.CONFIRM)),
) -> AIOutputOut:
    """仲裁员确认 AI 输出后才进入正式业务数据，对应 05/06/09 文档反复强调的人机协同原则。"""

    ai_output = await db.get(AIOutput, ai_output_id)
    if ai_output is None or ai_output.case_id != case_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI 输出不存在")

    ai_output.confirmed_at = datetime.now(timezone.utc)
    ai_output.confirmed_by = current_user.display_name
    await add_timeline_event(
        db,
        case_id=case_id,
        event_type="ai_confirm",
        summary=f"仲裁员确认 AI（{ai_output.capability}）输出",
        created_by=current_user.display_name,
    )
    await db.commit()
    await db.refresh(ai_output)
    return AIOutputOut.model_validate(ai_output)
