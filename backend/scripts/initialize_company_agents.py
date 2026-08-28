"""企业委托代理人数据库初始化脚本。

用法：
  python scripts/initialize_company_agents.py

功能：从所有内网案件快照中提取公司-代理人绑定记录，初始化数据库。
"""

import asyncio
import logging
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.session import SessionLocal
from app.services.company_agents import initialize_from_all_snapshots

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    logger.info("开始初始化企业委托代理人数据库...")

    async with SessionLocal() as session:
        try:
            inserted, updated = await initialize_from_all_snapshots(session)
            logger.info("✓ 初始化完成：新增 %d 条，更新 %d 条", inserted, updated)
            return 0
        except Exception as e:
            logger.exception("✗ 初始化失败")
            return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
