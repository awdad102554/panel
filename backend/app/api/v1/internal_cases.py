"""内网案件监控路由。

数据源是 internal_case_trackings 同步快照表(由后台定时任务全量 upsert),
紧急度在读取时用 internal_case_urgency.compute_urgency 按当前日期实时计算,不落库。
所有路由只要求登录。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.internal_case import (
    CaseTimeLimitOverride,
    InternalCaseTracking,
    InternalStage,
    SyncVerificationReport,
)
from app.models.user import User
from app.schemas.internal_case import (
    InternalCaseDetailOut,
    InternalCaseOut,
    InternalCaseUrgency,
    OverrideRequest,
    SyncResultOut,
)
from app.services.internal_case_sync import sync_internal_cases, verify_consistency
from app.services.time_limits import effective_settings
from app.services.internal_case_urgency import UrgencyResult, compute_urgency

router = APIRouter(prefix="/internal-cases", tags=["internal-cases"])


async def _load_overrides(db: AsyncSession) -> dict[str, CaseTimeLimitOverride]:
    """预载全部人工时效覆盖,按 external_case_id 索引。"""
    return {
        row.external_case_id: row
        for row in (await db.execute(select(CaseTimeLimitOverride))).scalars().all()
    }


def _build_out(
    row: InternalCaseTracking,
    override: CaseTimeLimitOverride | None,
    urgency: UrgencyResult,
) -> InternalCaseOut:
    payload = row.raw_payload or {}
    applicant = payload.get("applicant")
    respondent = payload.get("respondent")
    try:
        extension_days = int(payload.get("extension_days") or 0)
    except (TypeError, ValueError):
        extension_days = 0
    return InternalCaseOut(
        external_case_id=row.external_case_id,
        stage=row.stage,
        current_step=row.current_step,
        case_no=row.case_no,
        applicant=applicant if isinstance(applicant, str) and applicant else None,
        respondent=respondent if isinstance(respondent, str) and respondent else None,
        is_paused=row.is_paused,
        native_remaining_days=row.native_remaining_days,
        extension_days=extension_days,
        end_at=row.end_at,
        end_way=row.end_way,
        phase_entered_at=row.phase_entered_at,
        last_synced_at=row.last_synced_at,
        urgency=urgency.urgency,
        days_remaining=urgency.days_remaining,
        urgency_source=urgency.source,
        has_override=override is not None,
        override_deadline=override.deadline_override if override else None,
    )


@router.get("", response_model=list[InternalCaseOut])
async def list_internal_cases(
    stage: InternalStage | None = None,
    urgency: InternalCaseUrgency | None = None,
    include_closed: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[InternalCaseOut]:
    """监控列表:快照 + 实时紧急度,按紧急程度排序。

    默认排除 closed(已结案/已归档,终态)与 rejected(预约审核不通过已退回,
    等申请人补正)。
    """
    settings = await effective_settings(db)
    stmt = select(InternalCaseTracking)
    if stage is not None:
        stmt = stmt.where(InternalCaseTracking.stage == stage)
    rows = (await db.execute(stmt)).scalars().all()
    overrides = await _load_overrides(db)

    items: list[tuple[UrgencyResult, InternalCaseOut]] = []
    for row in rows:
        override = overrides.get(row.external_case_id)
        result = compute_urgency(row, override, settings)
        if result.urgency in ("closed", "rejected") and not include_closed:
            continue
        if urgency is not None and result.urgency != urgency:
            continue
        items.append((result, _build_out(row, override, result)))

    # 紧急度权重升序(超期最靠前);同档内剩余天数越少越靠前,无倒计时口径的排最后。
    items.sort(key=lambda item: (item[0].order, item[0].days_remaining is None, item[0].days_remaining or 0))
    return [out for _, out in items]


@router.post("/sync", response_model=SyncResultOut)
async def trigger_sync(
    full: bool = False,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> SyncResultOut:
    """手动触发一轮内网案件同步。

    默认轻量(筛选接口 + 消失案件单点补拉,秒级);full=True 全量翻页兜底
    (约 4 分钟,用于纠正轻量同步可能漏掉的边缘情况)。
    """
    counts = await sync_internal_cases(db, full=full)
    await db.commit()
    return SyncResultOut(counts=counts)


@router.post("/verify-consistency")
async def verify_sync_consistency(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> dict:
    """全量只读对账:比对内网全量数据与本地快照,验证轻量同步是否有遗漏。

    只拉取不修正数据;每次结果(统计+差异明细)落库到 sync_verification_reports,
    供事后排查轻量同步问题。耗时与全量同步相当(约几分钟),按需手动触发。
    """
    result = await verify_consistency(db)
    await db.commit()
    return result


@router.get("/verify-reports")
async def list_verify_reports(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[dict]:
    """历史一致性校验报告(新→旧),含完整差异明细,供排查轻量同步问题。"""
    stmt = (
        select(SyncVerificationReport)
        .order_by(SyncVerificationReport.created_at.desc())
        .limit(min(limit, 100))
    )
    reports = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(r.id),
            "created_at": r.created_at,
            "checked": r.checked,
            "missing_total": r.missing_total,
            "mismatch_total": r.mismatch_total,
            "only_in_snapshot": r.only_in_snapshot,
            "details": r.details,
        }
        for r in reports
    ]


@router.get("/{external_case_id}", response_model=InternalCaseDetailOut)
async def get_internal_case(
    external_case_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> InternalCaseDetailOut:
    """详情:合并内网原始 payload(含嵌套 cases 详情)与人工时效覆盖。"""
    settings = await effective_settings(db)
    stmt = select(InternalCaseTracking).where(
        InternalCaseTracking.external_case_id == external_case_id
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="内网案件不存在")

    override = await db.scalar(
        select(CaseTimeLimitOverride).where(
            CaseTimeLimitOverride.external_case_id == external_case_id
        )
    )
    result = compute_urgency(row, override, settings)
    base = _build_out(row, override, result)
    return InternalCaseDetailOut(
        **base.model_dump(),
        raw_payload=row.raw_payload,
        override_note=override.note if override else None,
    )


@router.put("/{external_case_id}/override", response_model=InternalCaseOut)
async def upsert_override(
    external_case_id: str,
    payload: OverrideRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InternalCaseOut:
    """设置/更新单个案件的人工时效覆盖(覆盖后以其为准,不再走默认阈值)。"""
    stmt = select(CaseTimeLimitOverride).where(
        CaseTimeLimitOverride.external_case_id == external_case_id
    )
    override = (await db.execute(stmt)).scalar_one_or_none()
    if override is None:
        override = CaseTimeLimitOverride(
            external_case_id=external_case_id,
            deadline_override=payload.deadline_override,
            note=payload.note,
            created_by=current_user.username,
        )
        db.add(override)
    else:
        override.deadline_override = payload.deadline_override
        override.note = payload.note
    await db.commit()

    return await _reload_out(db, external_case_id)


@router.delete("/{external_case_id}/override", status_code=status.HTTP_204_NO_CONTENT)
async def delete_override(
    external_case_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> None:
    """清除人工时效覆盖,恢复默认阈值口径。"""
    stmt = select(CaseTimeLimitOverride).where(
        CaseTimeLimitOverride.external_case_id == external_case_id
    )
    override = (await db.execute(stmt)).scalar_one_or_none()
    if override is not None:
        await db.delete(override)
        await db.commit()


async def _reload_out(db: AsyncSession, external_case_id: str) -> InternalCaseOut:
    """写操作后重载该案件的最新快照 + 紧急度,作为响应返回。"""
    settings = await effective_settings(db)
    stmt = select(InternalCaseTracking).where(
        InternalCaseTracking.external_case_id == external_case_id
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="内网案件不存在")
    override = await db.scalar(
        select(CaseTimeLimitOverride).where(
            CaseTimeLimitOverride.external_case_id == external_case_id
        )
    )
    result = compute_urgency(row, override, settings)
    return _build_out(row, override, result)
