"""企业委托代理人数据提取与查询服务。

核心功能：
1. 调用内网详情接口（caseData）获取代理人信息
2. 从 handle 阶段案件提取公司-代理人绑定
3. 增量更新（每次轻量同步后）
4. 查询：按公司名查代理人历史，按代理人名查代理过的案件

注意：列表接口（/arb/reserve、/arb/receive、/arb/handle）不返回 agents 字段，
必须调用详情接口才能获取完整的代理人信息。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.case_system.client import (
    CaseSystemClient,
    CaseSystemError,
    get_case_system_client,
)
from app.models.company_agent import CompanyAgentBinding
from app.models.internal_case import InternalCaseTracking, InternalStage

logger = logging.getLogger(__name__)

# 内网详情接口路径（与 internal_case_pause.py 相同）
_CASE_DATA_PATH = "/v1/api/admin/case/caseData"

# 代理人类型映射（与 case_submit.py 的 AGENT_TYPES 一致）
AGENT_TYPE_LABELS = {
    1: "法定代理人",
    2: "指定代理人",
    3: "近亲属",
    4: "团体推荐",
    5: "单位工作人员",
    6: "律师",
    7: "法律服务工作者",
}

# 内网时间戳是无时区本地时间(CST)
_INTRANET_TZ = timezone(timedelta(hours=8))


def _parse_dt(value) -> datetime | None:
    """解析内网时间戳（无时区本地时间）。"""
    if not value or not isinstance(value, str):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=_INTRANET_TZ)
        except ValueError:
            continue
    return None


async def _fetch_case_detail(
    client: CaseSystemClient, handle_row_id: str
) -> dict | None:
    """调用内网详情接口获取完整案件数据（包含 agents）。

    参数：
        handle_row_id: raw_payload.id（内网 handle 表的主键）

    返回：完整案件数据，失败返回 None
    """
    try:
        resp = await client.post(_CASE_DATA_PATH, json={"id": handle_row_id})
        if resp.status_code != 200:
            logger.warning(
                "获取案件详情失败 (handle_row_id=%s): HTTP %d",
                handle_row_id,
                resp.status_code,
            )
            return None

        body = resp.json()
        data = body.get("data") if isinstance(body, dict) else None

        if not isinstance(data, dict):
            logger.warning(
                "案件详情响应格式异常 (handle_row_id=%s)", handle_row_id
            )
            return None

        return data

    except CaseSystemError as exc:
        logger.warning("获取案件详情失败 (handle_row_id=%s): %s", handle_row_id, exc)
        return None
    except Exception as exc:
        logger.exception(
            "获取案件详情时发生异常 (handle_row_id=%s): %s", handle_row_id, exc
        )
        return None


def _extract_bindings_from_detail(
    detail_data: dict,
    external_case_id: str,
    case_no: str | None,
    filed_at: datetime | None,
) -> list[dict]:
    """从详情接口返回的数据提取公司-代理人绑定记录。

    参数：
        detail_data: caseData 接口返回的 data 字段
        external_case_id: 案件 ID (case_id)
        case_no: 案号
        filed_at: 立案时间

    返回：待插入/更新的绑定字典列表。
    """
    bindings: list[dict] = []

    # 1. 遍历被申请人（主要来源）
    for respondent in detail_data.get("respondent_arr") or []:
        if not isinstance(respondent, dict):
            continue

        # 判断是否为公司：有 social_code 或 company_nature 字段
        company_name = (respondent.get("name") or "").strip()
        is_company = bool(
            respondent.get("social_code") or respondent.get("company_nature")
        )

        if not company_name or not is_company:
            continue

        # 提取公司信息
        credit_code = (respondent.get("social_code") or "").strip() or None

        # 遍历该公司的代理人
        for agent in respondent.get("agents") or []:
            if not isinstance(agent, dict):
                continue

            agent_name = (agent.get("name") or "").strip()
            if not agent_name:
                continue

            # 代理人类型：type 字段是列表，取最后一个元素
            agent_type_list = agent.get("type")
            if not isinstance(agent_type_list, list) or not agent_type_list:
                continue
            agent_type = agent_type_list[-1]
            if agent_type not in AGENT_TYPE_LABELS:
                logger.warning(
                    "未知代理人类型 %s（案件 %s，代理人 %s），已跳过",
                    agent_type,
                    external_case_id,
                    agent_name,
                )
                continue

            # 提取代理人详细信息
            binding = {
                "company_name": company_name,
                "company_credit_code": credit_code,
                "agent_name": agent_name,
                "agent_type": agent_type,
                "agent_phone": (agent.get("mobile") or "").strip() or None,
                "agent_law_firm": (agent.get("law_firm_name") or "").strip() or None,
                "agent_id_number": (agent.get("id_number") or "").strip() or None,
                "party_role": "respondent",
                "external_case_id": external_case_id,
                "case_no": case_no,
                "filed_at": filed_at,
            }
            bindings.append(binding)

    # 2. 遍历申请人（当被申请人也是公司时，申请人为公司的情况）
    # 只在至少有一个被申请人是公司时才处理申请人公司
    has_company_respondent = any(
        bool((r.get("social_code") or r.get("company_nature")))
        for r in (detail_data.get("respondent_arr") or [])
        if isinstance(r, dict)
    )

    if has_company_respondent:
        for applicant in detail_data.get("applicant_arr") or []:
            if not isinstance(applicant, dict):
                continue

            company_name = (applicant.get("name") or "").strip()
            is_company = bool(
                applicant.get("social_code") or applicant.get("company_nature")
            )

            if not company_name or not is_company:
                continue

            credit_code = (applicant.get("social_code") or "").strip() or None

            for agent in applicant.get("agents") or []:
                if not isinstance(agent, dict):
                    continue

                agent_name = (agent.get("name") or "").strip()
                if not agent_name:
                    continue

                agent_type_list = agent.get("type")
                if not isinstance(agent_type_list, list) or not agent_type_list:
                    continue
                agent_type = agent_type_list[-1]
                if agent_type not in AGENT_TYPE_LABELS:
                    continue

                binding = {
                    "company_name": company_name,
                    "company_credit_code": credit_code,
                    "agent_name": agent_name,
                    "agent_type": agent_type,
                    "agent_phone": (agent.get("mobile") or "").strip() or None,
                    "agent_law_firm": (agent.get("law_firm_name") or "").strip()
                    or None,
                    "agent_id_number": (agent.get("id_number") or "").strip() or None,
                    "party_role": "applicant",
                    "external_case_id": external_case_id,
                    "case_no": case_no,
                    "filed_at": filed_at,
                }
                bindings.append(binding)

    return bindings


async def extract_and_upsert_bindings(
    session: AsyncSession,
    tracking_rows: list[InternalCaseTracking],
    client: CaseSystemClient | None = None,
    *,
    auto_commit: bool = False,
) -> tuple[int, int]:
    """从 handle 阶段案件提取公司-代理人绑定并 UPSERT 到数据库。

    注意：只处理 handle 阶段的案件，因为只有这个阶段的案件有 raw_payload.id
    可以用来调用详情接口。

    参数：
        auto_commit: 是否自动提交（默认 False）。
                    在同步流程中调用时应为 False，由调用方统一提交；
                    在独立脚本中调用时可为 True。

    返回：(新增数, 更新数)
    """
    client = client or get_case_system_client()
    inserted_count = 0
    updated_count = 0

    for row in tracking_rows:
        # 只处理 handle 阶段的案件
        if row.stage != InternalStage.HANDLE:
            continue

        if not row.raw_payload:
            continue

        # 获取 handle_row_id（内网 handle 表主键）
        handle_row_id = row.raw_payload.get("id")
        if handle_row_id is None:
            logger.warning(
                "案件 %s 的 raw_payload 中没有 id 字段", row.external_case_id
            )
            continue

        # 调用详情接口获取完整数据
        detail_data = await _fetch_case_detail(client, handle_row_id)
        if not detail_data:
            continue

        # 提取立案时间
        filed_at = _parse_dt(detail_data.get("handle_at")) or _parse_dt(
            detail_data.get("receive_at")
        )

        bindings = _extract_bindings_from_detail(
            detail_data=detail_data,
            external_case_id=row.external_case_id,
            case_no=row.case_no,
            filed_at=filed_at,
        )

        if not bindings:
            continue

        # 批量检查现有绑定
        keys = [
            (b["company_name"], b["agent_name"], b["external_case_id"])
            for b in bindings
        ]
        existing_stmt = select(CompanyAgentBinding).where(
            or_(
                *[
                    and_(
                        CompanyAgentBinding.company_name == k[0],
                        CompanyAgentBinding.agent_name == k[1],
                        CompanyAgentBinding.external_case_id == k[2],
                    )
                    for k in keys
                ]
            )
        )
        existing_result = await session.execute(existing_stmt)
        existing_map = {
            (e.company_name, e.agent_name, e.external_case_id): e
            for e in existing_result.scalars().all()
        }

        # UPSERT
        for binding in bindings:
            key = (
                binding["company_name"],
                binding["agent_name"],
                binding["external_case_id"],
            )
            existing = existing_map.get(key)

            if existing:
                # 更新时间戳（其他字段保持不变）
                existing.updated_at = datetime.now(timezone.utc)
                updated_count += 1
            else:
                # 新增
                session.add(CompanyAgentBinding(**binding))
                inserted_count += 1

    if auto_commit:
        await session.commit()

    return inserted_count, updated_count


async def autocomplete_company_names(
    session: AsyncSession, query: str, limit: int = 10
) -> list[str]:
    """公司名称自动补全（模糊匹配）。

    参数：
        query: 搜索关键词
        limit: 返回数量上限

    返回：匹配的公司名称列表（按名称字典序）
    """
    if not query or not query.strip():
        return []

    keyword = query.strip()

    stmt = (
        select(CompanyAgentBinding.company_name)
        .where(CompanyAgentBinding.company_name.like(f"%{keyword}%"))
        .group_by(CompanyAgentBinding.company_name)
        .order_by(CompanyAgentBinding.company_name)
        .limit(limit)
    )

    result = await session.execute(stmt)
    return [row[0] for row in result.all()]


async def autocomplete_agent_names(
    session: AsyncSession, query: str, limit: int = 10
) -> list[str]:
    """代理人姓名自动补全（模糊匹配）。

    参数：
        query: 搜索关键词
        limit: 返回数量上限

    返回：匹配的代理人姓名列表（按姓名字典序）
    """
    if not query or not query.strip():
        return []

    keyword = query.strip()

    stmt = (
        select(CompanyAgentBinding.agent_name)
        .where(CompanyAgentBinding.agent_name.like(f"%{keyword}%"))
        .group_by(CompanyAgentBinding.agent_name)
        .order_by(CompanyAgentBinding.agent_name)
        .limit(limit)
    )

    result = await session.execute(stmt)
    return [row[0] for row in result.all()]


async def initialize_from_all_snapshots(session: AsyncSession) -> tuple[int, int]:
    """从所有 handle 阶段案件初始化企业代理人数据库（一次性操作）。

    注意：只处理 handle 阶段的案件，需要调用详情接口获取代理人信息。
    这是一个较慢的操作，因为每个案件都需要调用一次详情接口。

    返回：(新增数, 更新数)
    """
    logger.info("开始从所有 handle 案件初始化企业代理人数据库...")

    client = get_case_system_client()

    # 只查询 handle 阶段的案件
    stmt = select(InternalCaseTracking).where(
        InternalCaseTracking.stage == InternalStage.HANDLE
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()

    total_cases = len(rows)
    logger.info("共找到 %d 个 handle 阶段案件", total_cases)

    # 分批处理，避免内存溢出
    batch_size = 50
    total_inserted = 0
    total_updated = 0

    for i in range(0, total_cases, batch_size):
        batch = rows[i : i + batch_size]
        inserted, updated = await extract_and_upsert_bindings(
            session, batch, client, auto_commit=True
        )
        total_inserted += inserted
        total_updated += updated

        logger.info(
            "已处理 %d/%d 案件，本批新增 %d，更新 %d",
            min(i + batch_size, total_cases),
            total_cases,
            inserted,
            updated,
        )

    logger.info(
        "企业代理人数据库初始化完成：共新增 %d 条，更新 %d 条",
        total_inserted,
        total_updated,
    )
    return total_inserted, total_updated


async def list_agents_by_company(
    session: AsyncSession,
    company_name: str,
) -> list[dict]:
    """查询某公司历年使用的所有代理人（按最近立案时间倒序）。

    返回：[{
        agent_name, agent_type, agent_type_label, agent_phone, agent_law_firm,
        case_no, filed_at, external_case_id, party_role
    }, ...]
    """
    stmt = (
        select(CompanyAgentBinding)
        .where(CompanyAgentBinding.company_name.like(f"%{company_name}%"))
        .order_by(CompanyAgentBinding.filed_at.desc())
    )
    result = await session.execute(stmt)
    bindings = result.scalars().all()

    return [
        {
            "agent_name": b.agent_name,
            "agent_type": b.agent_type,
            "agent_type_label": AGENT_TYPE_LABELS.get(b.agent_type, "未知"),
            "agent_phone": b.agent_phone,
            "agent_law_firm": b.agent_law_firm,
            "agent_id_number": b.agent_id_number,
            "case_no": b.case_no,
            "filed_at": b.filed_at,
            "external_case_id": b.external_case_id,
            "party_role": b.party_role,
            "company_name": b.company_name,
            "company_credit_code": b.company_credit_code,
        }
        for b in bindings
    ]


async def list_cases_by_agent(
    session: AsyncSession,
    agent_name: str,
) -> list[dict]:
    """查询某代理人历年代理过的所有案件（按最近立案时间倒序）。

    返回：[{
        company_name, company_credit_code, agent_type, agent_type_label,
        case_no, filed_at, external_case_id, party_role
    }, ...]
    """
    stmt = (
        select(CompanyAgentBinding)
        .where(CompanyAgentBinding.agent_name.like(f"%{agent_name}%"))
        .order_by(CompanyAgentBinding.filed_at.desc())
    )
    result = await session.execute(stmt)
    bindings = result.scalars().all()

    return [
        {
            "company_name": b.company_name,
            "company_credit_code": b.company_credit_code,
            "agent_name": b.agent_name,
            "agent_type": b.agent_type,
            "agent_type_label": AGENT_TYPE_LABELS.get(b.agent_type, "未知"),
            "agent_phone": b.agent_phone,
            "agent_law_firm": b.agent_law_firm,
            "case_no": b.case_no,
            "filed_at": b.filed_at,
            "external_case_id": b.external_case_id,
            "party_role": b.party_role,
        }
        for b in bindings
    ]
