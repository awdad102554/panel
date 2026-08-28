"""企业委托代理人数据库查询接口。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import SessionLocal, get_db
from app.models.user import User
from app.services.company_agents import (
    autocomplete_agent_names,
    autocomplete_company_names,
    initialize_from_all_snapshots,
    list_agents_by_company,
    list_cases_by_agent,
)

router = APIRouter(prefix="/company-agents", tags=["company-agents"])
logger = logging.getLogger(__name__)


class AgentInfo(BaseModel):
    """代理人信息。"""

    agent_name: str
    agent_type: int
    agent_type_label: str
    agent_phone: str | None
    agent_law_firm: str | None
    agent_id_number: str | None
    case_no: str | None
    filed_at: str | None  # ISO格式
    external_case_id: str
    party_role: str
    company_name: str
    company_credit_code: str | None


class CaseInfo(BaseModel):
    """案件信息。"""

    company_name: str
    company_credit_code: str | None
    agent_name: str
    agent_type: int
    agent_type_label: str
    agent_phone: str | None
    agent_law_firm: str | None
    case_no: str | None
    filed_at: str | None  # ISO格式
    external_case_id: str
    party_role: str


class CompanyAgentsResponse(BaseModel):
    """按公司查询代理人响应。"""

    company_name: str
    total: int
    agents: list[AgentInfo]


class AgentCasesResponse(BaseModel):
    """按代理人查询案件响应。"""

    agent_name: str
    total: int
    cases: list[CaseInfo]


class InitializeResponse(BaseModel):
    """初始化响应。"""

    success: bool
    inserted: int
    updated: int
    message: str


@router.get("/by-company", response_model=CompanyAgentsResponse)
async def get_agents_by_company(
    company_name: str = Query(..., description="公司名称（支持模糊匹配）"),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> CompanyAgentsResponse:
    """查询某公司历年使用的所有代理人（按最近立案时间倒序）。"""
    agents_data = await list_agents_by_company(db, company_name)

    agents = [
        AgentInfo(
            agent_name=a["agent_name"],
            agent_type=a["agent_type"],
            agent_type_label=a["agent_type_label"],
            agent_phone=a["agent_phone"],
            agent_law_firm=a["agent_law_firm"],
            agent_id_number=a["agent_id_number"],
            case_no=a["case_no"],
            filed_at=a["filed_at"].isoformat() if a["filed_at"] else None,
            external_case_id=a["external_case_id"],
            party_role=a["party_role"],
            company_name=a["company_name"],
            company_credit_code=a["company_credit_code"],
        )
        for a in agents_data
    ]

    return CompanyAgentsResponse(
        company_name=company_name,
        total=len(agents),
        agents=agents,
    )


@router.get("/by-agent", response_model=AgentCasesResponse)
async def get_cases_by_agent(
    agent_name: str = Query(..., description="代理人姓名（支持模糊匹配）"),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> AgentCasesResponse:
    """查询某代理人历年代理过的所有案件（按最近立案时间倒序）。"""
    cases_data = await list_cases_by_agent(db, agent_name)

    cases = [
        CaseInfo(
            company_name=c["company_name"],
            company_credit_code=c["company_credit_code"],
            agent_name=c["agent_name"],
            agent_type=c["agent_type"],
            agent_type_label=c["agent_type_label"],
            agent_phone=c["agent_phone"],
            agent_law_firm=c["agent_law_firm"],
            case_no=c["case_no"],
            filed_at=c["filed_at"].isoformat() if c["filed_at"] else None,
            external_case_id=c["external_case_id"],
            party_role=c["party_role"],
        )
        for c in cases_data
    ]

    return AgentCasesResponse(
        agent_name=agent_name,
        total=len(cases),
        cases=cases,
    )


@router.get("/autocomplete/companies")
async def autocomplete_companies(
    q: str = Query("", description="搜索关键词"),
    limit: int = Query(10, ge=1, le=50, description="返回数量上限"),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[str]:
    """公司名称自动补全（模糊匹配）。"""
    if not q or not q.strip():
        return []
    return await autocomplete_company_names(db, q, limit)


@router.get("/autocomplete/agents")
async def autocomplete_agents(
    q: str = Query("", description="搜索关键词"),
    limit: int = Query(10, ge=1, le=50, description="返回数量上限"),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[str]:
    """代理人姓名自动补全（模糊匹配）。"""
    if not q or not q.strip():
        return []
    return await autocomplete_agent_names(db, q, limit)


@router.post("/initialize", response_model=InitializeResponse)
async def initialize_database(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> InitializeResponse:
    """从所有快照初始化企业代理人数据库（一次性操作，需管理员权限）。

    ⚠️ 警告：此接口已废弃，不建议通过 HTTP 调用。
    原因：
    1. 会同步处理上千案件，必然超过 nginx/浏览器超时
    2. 不持 SYNC_LOCK，与轻量同步并发写会冲突
    3. 同步调用详情接口速度慢

    建议：使用 backend/scripts/initialize_company_agents.py 脚本初始化。
    """
    from fastapi import HTTPException

    raise HTTPException(
        status_code=501,
        detail="此接口已废弃。请使用 backend/scripts/initialize_company_agents.py 脚本进行初始化。",
    )
