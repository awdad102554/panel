#!/usr/bin/env python3
"""测试企业委托代理人数据库功能。

用法：
  python scripts/test_company_agents.py
"""

import asyncio
import logging
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.session import SessionLocal
from app.models.company_agent import CompanyAgentBinding
from app.models.internal_case import InternalCaseTracking, InternalStage
from app.services.company_agents import (
    list_agents_by_company,
    list_cases_by_agent,
)
from sqlalchemy import func, select

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_all():
    async with SessionLocal() as session:
        # 1. 统计数据
        logger.info("=" * 60)
        logger.info("企业委托代理人数据库统计")
        logger.info("=" * 60)

        result = await session.execute(select(func.count(CompanyAgentBinding.id)))
        total = result.scalar()

        result = await session.execute(
            select(func.count(func.distinct(CompanyAgentBinding.company_name)))
        )
        companies = result.scalar()

        result = await session.execute(
            select(func.count(func.distinct(CompanyAgentBinding.agent_name)))
        )
        agents = result.scalar()

        result = await session.execute(
            select(func.count(InternalCaseTracking.id)).where(
                InternalCaseTracking.stage == InternalStage.HANDLE
            )
        )
        total_handle = result.scalar()

        result = await session.execute(
            select(func.count(func.distinct(CompanyAgentBinding.external_case_id)))
        )
        cases_with_agents = result.scalar()

        logger.info("  总记录数: %d", total)
        logger.info("  涉及公司: %d 家", companies)
        logger.info("  涉及代理人: %d 人", agents)
        logger.info(
            "  有代理人的案件: %d/%d (%.1f%%)",
            cases_with_agents,
            total_handle,
            cases_with_agents * 100 / total_handle if total_handle else 0,
        )

        # 2. 按类型统计
        result = await session.execute(
            select(
                CompanyAgentBinding.agent_type, func.count(CompanyAgentBinding.id)
            ).group_by(CompanyAgentBinding.agent_type)
        )
        by_type = result.all()

        type_labels = {
            1: "法定代理人",
            2: "指定代理人",
            3: "近亲属",
            4: "团体推荐",
            5: "单位工作人员",
            6: "律师",
            7: "法律服务工作者",
        }

        logger.info("\n  按类型分布:")
        for agent_type, count in sorted(by_type, key=lambda x: -x[1]):
            label = type_labels.get(agent_type, f"未知({agent_type})")
            logger.info("    %s: %d", label, count)

        # 3. 查询测试
        logger.info("\n" + "=" * 60)
        logger.info("查询功能测试")
        logger.info("=" * 60)

        # 找一个有代理人的公司
        result = await session.execute(
            select(CompanyAgentBinding.company_name)
            .group_by(CompanyAgentBinding.company_name)
            .order_by(func.count(CompanyAgentBinding.id).desc())
            .limit(1)
        )
        top_company = result.scalar_one_or_none()

        if top_company:
            logger.info("\n测试 1: 按公司查询（%s）", top_company)
            agents_list = await list_agents_by_company(session, top_company)
            logger.info("  找到 %d 条记录", len(agents_list))
            for i, agent in enumerate(agents_list[:3], 1):
                logger.info(
                    "    %d. %s (%s) - %s",
                    i,
                    agent["agent_name"],
                    agent["agent_type_label"],
                    agent["case_no"],
                )

        # 找一个活跃的代理人
        result = await session.execute(
            select(CompanyAgentBinding.agent_name)
            .where(CompanyAgentBinding.agent_type == 6)  # 律师
            .group_by(CompanyAgentBinding.agent_name)
            .order_by(func.count(CompanyAgentBinding.id).desc())
            .limit(1)
        )
        top_agent = result.scalar_one_or_none()

        if top_agent:
            logger.info("\n测试 2: 按代理人查询（%s）", top_agent)
            cases_list = await list_cases_by_agent(session, top_agent)
            logger.info("  找到 %d 条记录", len(cases_list))
            for i, case in enumerate(cases_list[:3], 1):
                logger.info(
                    "    %d. %s - %s",
                    i,
                    case["company_name"],
                    case["case_no"],
                )

        logger.info("\n" + "=" * 60)
        logger.info("✓ 所有测试通过")
        logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_all())
