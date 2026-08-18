"""AI 预约审查编排:非流式跑一遍审查并落库,供手动流式端点与后台自动审核复用。

复用 app/services/reserve_review.py 的纯函数(抓详情/结构化摘要/提示词/结果解析),
这里只做编排:抓详情 → 组装 → 读启用模型 → 调 LLM → 解析 → 落库。结论仅作初筛建议。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm import LLMCallError, chat_completion
from app.integrations.case_system.client import get_case_system_client
from app.models.internal_case import InternalCaseTracking, InternalStage
from app.models.reserve_ai_review import ReserveAIReview
from app.repositories import ai_model_repository
from app.services import reserve_review as review_service

logger = logging.getLogger(__name__)

# 有效结论:自动审核据此判断"是否已审出结果"(审查失败不算,下轮重试)。
_VALID_CONCLUSIONS = ("通过", "补正", "驳回")


async def pending_reserve_rows(db: AsyncSession) -> list[InternalCaseTracking]:
    """待审核预约案件(快照 stage=reserve 且 raw_payload.status==0)。"""
    rows = (
        await db.execute(
            select(InternalCaseTracking).where(InternalCaseTracking.stage == InternalStage.RESERVE)
        )
    ).scalars().all()
    return [r for r in rows if (r.raw_payload or {}).get("status") == 0]


def latest_review_map(rows: list[tuple[str, str]]) -> dict[str, str]:
    """(external_case_id, conclusion) 按 created_at 倒序传入,取每案最近一次结论。

    纯函数,便于单测。返回 {external_case_id: 最近一次 conclusion}。
    """
    out: dict[str, str] = {}
    for ext_id, conclusion in rows:
        if ext_id not in out:
            out[ext_id] = conclusion
    return out


def is_valid_conclusion(conclusion: str | None) -> bool:
    """结论是否有效(通过/补正/驳回);审查失败/None 视为无效,自动审核据此重试。"""
    return conclusion in _VALID_CONCLUSIONS


async def latest_reviews(db: AsyncSession) -> dict[str, str]:
    rows = (
        await db.execute(
            select(ReserveAIReview.external_case_id, ReserveAIReview.conclusion).order_by(
                ReserveAIReview.created_at.desc()
            )
        )
    ).all()
    return latest_review_map(rows)


async def valid_reviewed_ids(db: AsyncSession) -> set[str]:
    """已审出有效结论(通过/补正/驳回)的案件 external_case_id 集合。

    整个历史中只要有过一次有效结论就不再自动重审(即便最近一次是「审查失败」)。
    """
    rows = await db.execute(
        select(ReserveAIReview.external_case_id)
        .where(ReserveAIReview.conclusion.in_(_VALID_CONCLUSIONS))
        .distinct()
    )
    return {r[0] for r in rows.all()}


async def save_review(
    db: AsyncSession,
    *,
    external_case_id: str,
    reserve_row_id: int,
    applicant: str,
    respondent: str,
    case_reason: str | None,
    result: dict[str, Any],
    snapshot: dict[str, Any],
    model_name: str | None,
    created_by: str,
) -> ReserveAIReview:
    """落库一次审查留痕,返回已刷新(含 id/created_at)的 ORM 行。"""
    row = ReserveAIReview(
        external_case_id=external_case_id,
        reserve_row_id=reserve_row_id,
        applicant=applicant,
        respondent=respondent,
        case_reason=case_reason,
        conclusion=result["conclusion"],
        reason=result["reason"],
        issues=result["issues"],
        missing_materials=result["missing_materials"],
        rule_refs=result["rule_refs"],
        checks=result.get("checks", []),
        model_name=model_name,
        case_snapshot=snapshot,
        raw_result=result,
        created_by=created_by,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def run_review(
    db: AsyncSession,
    *,
    external_case_id: str,
    reserve_row_id: int,
    applicant: str,
    respondent: str,
    case_reason: str | None,
    created_by: str,
) -> ReserveAIReview:
    """非流式完整审查一件预约案件并落库(抓详情→组装→调模型→解析→保存)。

    无启用模型 / LLM 调用失败均落「审查失败」留痕;抓详情失败抛 CaseSystemError,
    由调用方决定是否重试。
    """
    client = get_case_system_client()
    detail = await review_service.fetch_reserve_detail(client, int(reserve_row_id))
    snapshot = review_service.build_case_payload(detail)
    messages = review_service.build_messages(snapshot)

    model_config = await ai_model_repository.get_enabled_model(db)
    if model_config is None:
        result = review_service.failure_result("未配置生效的 AI 模型，请先在「模型管理」启用")
        model_name = None
    else:
        model_name = model_config.model_name
        try:
            text = await chat_completion(messages, model_config)
        except LLMCallError as exc:
            result = review_service.failure_result(str(exc))
        else:
            result = review_service.parse_result(text)

    return await save_review(
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


async def auto_review_pending(db: AsyncSession) -> int:
    """对「尚未审出有效结论」的待审核预约案件各自动审查一次,返回本次审查件数。

    未配置启用模型时直接返回 0(不刷「审查失败」留痕,避免无意义记录)。
    只有历史上有过 通过/补正/驳回 的案件才停止自动重审;仅「审查失败」的下轮重试。
    """
    if await ai_model_repository.get_enabled_model(db) is None:
        return 0

    pending = await pending_reserve_rows(db)
    if not pending:
        return 0

    valid_ids = await valid_reviewed_ids(db)
    # 先把要审的案件压成普通 dict(而非持有 ORM 对象)——下面 run_review 会逐件 commit,
    # 提交后 session 会 expire 对象,若再碰 row.raw_payload 会触发回查甚至 ObjectDeletedError。
    todo: list[dict[str, Any]] = []
    for row in pending:
        if row.external_case_id in valid_ids:
            continue
        p = row.raw_payload or {}
        reserve_row_id = p.get("id")
        if reserve_row_id is None:
            logger.warning("预约案件 %s 缺少内网行 id,跳过自动审核", row.external_case_id)
            continue
        cases = p.get("cases") if isinstance(p.get("cases"), dict) else {}
        todo.append(
            {
                "external_case_id": row.external_case_id,
                "reserve_row_id": int(reserve_row_id),
                "applicant": p.get("applicant") or "",
                "respondent": p.get("respondent") or "",
                "case_reason": cases.get("case_reason"),
            }
        )

    count = 0
    for item in todo:
        try:
            await run_review(db=db, created_by="系统", **item)
            count += 1
        except Exception:
            # 单案失败不中断整轮(抓详情/落库异常等),下轮重试。
            logger.exception("预约案件 %s 自动审核失败", item["external_case_id"])
    return count
