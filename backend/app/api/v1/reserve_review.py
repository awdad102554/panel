"""AI 预约审查路由。

- GET  /reserve-reviews/pending            待审核预约案件列表(快照 status=0)
- POST /reserve-reviews/{id}/review        流式审查一件(NDJSON 逐步事件 + 结论),落库留痕
- GET  /reserve-reviews/{id}               该案件最近一次审查结果

审查结论仅作初筛建议,不写回内网审批(人机分工)。
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm import LLMCallError, chat_completion
from app.api.deps import get_current_user
from app.core.permissions import Action, require_permission
from app.db.session import SessionLocal, get_db
from app.integrations.case_system.client import CaseSystemError, get_case_system_client
from app.models.internal_case import InternalCaseTracking, InternalStage
from app.models.reserve_ai_review import ReserveAIReview
from app.models.reserve_review_decision import ReserveReviewDecision
from app.models.user import User
from app.repositories import ai_model_repository
from app.schemas.reserve_review import (
    PendingReserveOut,
    ReserveCaseDetailOut,
    ReserveReviewDecisionCreate,
    ReserveReviewDecisionOut,
    ReserveReviewOut,
)
from app.services import reserve_review as review_service
from app.services import reserve_review_runner as runner

router = APIRouter(prefix="/reserve-reviews", tags=["reserve-review"])
logger = logging.getLogger(__name__)


def _ndjson(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False) + "\n"


async def _save_review(
    *,
    external_case_id: str,
    reserve_row_id: int,
    applicant: str,
    respondent: str,
    case_reason: str | None,
    result: dict,
    snapshot: dict,
    model_name: str | None,
    created_by: str,
) -> ReserveAIReview:
    """落库一次审查留痕,返回已刷新(含 id/created_at)的 ORM 行。"""
    async with SessionLocal() as db:
        return await runner.save_review(
            db=db,
            external_case_id=external_case_id,
            reserve_row_id=reserve_row_id,
            applicant=applicant,
            respondent=respondent,
            case_reason=case_reason,
            result=result,
            snapshot=snapshot,
            model_name=model_name,
            created_by=created_by,
        )


@router.get("/pending", response_model=list[PendingReserveOut])
async def list_pending_reserves(
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_permission(Action.VIEW)),
) -> list[PendingReserveOut]:
    rows = await runner.pending_reserve_rows(db)
    latest = await runner.latest_reviews(db)
    out: list[PendingReserveOut] = []
    for row in rows:
        p = row.raw_payload or {}
        cases = p.get("cases") if isinstance(p.get("cases"), dict) else {}
        out.append(
            PendingReserveOut(
                external_case_id=row.external_case_id,
                reserve_row_id=p.get("id"),
                applicant=p.get("applicant") or "",
                respondent=p.get("respondent") or "",
                reserve_at=p.get("reserve_at") or p.get("submit_at"),
                case_reason=cases.get("case_reason"),
                reserve_time_limit=p.get("reserve_time_limit"),
                has_review=row.external_case_id in latest,
                latest_conclusion=latest.get(row.external_case_id),
            )
        )
    out.sort(key=lambda x: x.reserve_at or "", reverse=True)
    return out


@router.post("/{external_case_id}/review")
async def review_reserve(
    external_case_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Action.AI_INVOKE)),
) -> StreamingResponse:
    row = (
        await db.execute(
            select(InternalCaseTracking).where(
                InternalCaseTracking.external_case_id == external_case_id
            )
        )
    ).scalar_one_or_none()
    if row is None or row.stage != InternalStage.RESERVE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="预约案件不存在")

    p = row.raw_payload or {}
    row_id = p.get("id")
    if row_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="预约案件缺少内网行 id")
    cases = p.get("cases") if isinstance(p.get("cases"), dict) else {}
    applicant = p.get("applicant") or ""
    respondent = p.get("respondent") or ""
    case_reason = cases.get("case_reason")
    created_by = current_user.username

    async def event_stream():
        client = get_case_system_client()

        # 1) 抓详情
        yield _ndjson({"type": "step", "key": "fetch_detail", "label": "抓取预约详情", "status": "running"})
        try:
            detail = await review_service.fetch_reserve_detail(client, int(row_id))
        except CaseSystemError as exc:
            yield _ndjson({"type": "step", "key": "fetch_detail", "label": "抓取预约详情", "status": "error", "detail": str(exc)})
            yield _ndjson({"type": "result", "data": review_service.failure_result(f"抓取预约详情失败：{exc}")})
            return
        yield _ndjson({"type": "step", "key": "fetch_detail", "label": "抓取预约详情", "status": "done", "detail": "已获取当事人 / 仲裁请求 / 事实理由 / 证据材料"})

        # 2) 组装提示词
        yield _ndjson({"type": "step", "key": "build_prompt", "label": "组装审查提示词", "status": "running"})
        snapshot = review_service.build_case_payload(detail)
        messages = review_service.build_messages(snapshot)
        yield _ndjson({"type": "step", "key": "build_prompt", "label": "组装审查提示词", "status": "done", "detail": "审查规则 + 案件结构化摘要已就绪"})

        # 3) 读取启用模型
        async with SessionLocal() as s:
            model_config = await ai_model_repository.get_enabled_model(s)
        if model_config is None:
            result = review_service.failure_result("未配置生效的 AI 模型，请先在「模型管理」启用")
            yield _ndjson({"type": "step", "key": "call_llm", "label": "调用 AI 模型", "status": "error", "detail": "未配置生效模型"})
            await _save_review(
                external_case_id=external_case_id,
                reserve_row_id=int(row_id),
                applicant=applicant,
                respondent=respondent,
                case_reason=case_reason,
                result=result,
                snapshot=snapshot,
                model_name=None,
                created_by=created_by,
            )
            yield _ndjson({"type": "result", "data": result})
            return
        model_name = model_config.model_name

        # 4) 调模型
        yield _ndjson({"type": "step", "key": "call_llm", "label": f"调用 AI 模型（{model_name}）", "status": "running"})
        try:
            text = await chat_completion(messages, model_config)
        except LLMCallError as exc:
            yield _ndjson({"type": "step", "key": "call_llm", "label": f"调用 AI 模型（{model_name}）", "status": "error", "detail": str(exc)})
            result = review_service.failure_result(str(exc))
            await _save_review(
                external_case_id=external_case_id,
                reserve_row_id=int(row_id),
                applicant=applicant,
                respondent=respondent,
                case_reason=case_reason,
                result=result,
                snapshot=snapshot,
                model_name=model_name,
                created_by=created_by,
            )
            yield _ndjson({"type": "result", "data": result})
            return
        yield _ndjson({"type": "step", "key": "call_llm", "label": f"调用 AI 模型（{model_name}）", "status": "done"})

        # 5) 解析
        yield _ndjson({"type": "step", "key": "parse", "label": "解析审查结论", "status": "running"})
        result = review_service.parse_result(text)
        yield _ndjson({"type": "step", "key": "parse", "label": "解析审查结论", "status": "done", "detail": f"结论：{result['conclusion']}"})

        # 6) 落库 + 返回
        stored = await _save_review(
            external_case_id=external_case_id,
            reserve_row_id=int(row_id),
            applicant=applicant,
            respondent=respondent,
            case_reason=case_reason,
            result=result,
            snapshot=snapshot,
            model_name=model_name,
            created_by=created_by,
        )
        data = ReserveReviewOut.model_validate(stored).model_dump(mode="json")
        yield _ndjson({"type": "result", "data": data})

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@router.get("/{external_case_id}/detail", response_model=ReserveCaseDetailOut)
async def get_reserve_case_detail(
    external_case_id: str,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_permission(Action.VIEW)),
) -> ReserveCaseDetailOut:
    """实时拉内网预约详情并结构化返回,供前端「查看案件」弹窗展示。"""
    row = (
        await db.execute(
            select(InternalCaseTracking).where(
                InternalCaseTracking.external_case_id == external_case_id
            )
        )
    ).scalar_one_or_none()
    if row is None or row.stage != InternalStage.RESERVE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="预约案件不存在")

    p = row.raw_payload or {}
    row_id = p.get("id")
    if row_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="预约案件缺少内网行 id")
    cases = p.get("cases") if isinstance(p.get("cases"), dict) else {}

    client = get_case_system_client()
    try:
        detail = await review_service.fetch_reserve_detail(client, int(row_id))
    except CaseSystemError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"抓取预约详情失败：{exc}")

    return ReserveCaseDetailOut(
        external_case_id=external_case_id,
        reserve_row_id=int(row_id),
        applicant=p.get("applicant") or "",
        respondent=p.get("respondent") or "",
        case_reason=cases.get("case_reason"),
        reserve_at=p.get("reserve_at") or p.get("submit_at"),
        reserve_time_limit=p.get("reserve_time_limit"),
        detail=review_service.build_case_payload(detail),
    )


@router.get("/{external_case_id}", response_model=ReserveReviewOut)
async def get_latest_review(
    external_case_id: str,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_permission(Action.VIEW)),
) -> ReserveReviewOut:
    row = (
        await db.execute(
            select(ReserveAIReview)
            .where(ReserveAIReview.external_case_id == external_case_id)
            .order_by(ReserveAIReview.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该案件尚无审查记录")
    return ReserveReviewOut.model_validate(row)


@router.get("/{external_case_id}/decision", response_model=ReserveReviewDecisionOut)
async def get_latest_decision(
    external_case_id: str,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_permission(Action.VIEW)),
) -> ReserveReviewDecisionOut:
    """该案件最近一次人工审核结果(同意/不同意 + 理由);无记录 404。"""
    row = (
        await db.execute(
            select(ReserveReviewDecision)
            .where(ReserveReviewDecision.external_case_id == external_case_id)
            .order_by(ReserveReviewDecision.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该案件尚无人工审核结果")
    return ReserveReviewDecisionOut.model_validate(row)


@router.post("/{external_case_id}/decision", response_model=ReserveReviewDecisionOut, status_code=status.HTTP_201_CREATED)
async def submit_decision(
    external_case_id: str,
    payload: ReserveReviewDecisionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Action.CONFIRM)),
) -> ReserveReviewDecisionOut:
    """保存一件预约案件的人工审核结果(本地留痕,追加式,最新一条生效)。

    TODO(内网提交): 待提供提交审核的请求体后,在此处补 POST 内网接口;本次仅落本地。
    """
    row = (
        await db.execute(
            select(InternalCaseTracking).where(
                InternalCaseTracking.external_case_id == external_case_id
            )
        )
    ).scalar_one_or_none()
    if row is None or row.stage != InternalStage.RESERVE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="预约案件不存在")

    p = row.raw_payload or {}
    reserve_row_id = p.get("id")
    if reserve_row_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="预约案件缺少内网行 id")
    cases = p.get("cases") if isinstance(p.get("cases"), dict) else {}

    decision = payload.decision
    reject_reason = payload.reject_reason if decision == "不同意" else None
    reject_detail = payload.reject_detail if decision == "不同意" else None

    rec = ReserveReviewDecision(
        external_case_id=external_case_id,
        reserve_row_id=int(reserve_row_id),
        applicant=p.get("applicant") or "",
        respondent=p.get("respondent") or "",
        case_reason=cases.get("case_reason"),
        decision=decision,
        reject_reason=reject_reason,
        reject_detail=reject_detail,
        created_by=current_user.username,
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return ReserveReviewDecisionOut.model_validate(rec)
