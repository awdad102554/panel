"""预登记案件存储:独立的 SQLite 文件数据库,与主库(PostgreSQL)完全分离。

预登记案件(页面显示名"预登记案件")用于"暂不录入内网系统"的案件登记(2026-08-07 需求),数据文件为
backend/data/virtual_cases.db。表结构启动时自动创建(create_all),不走 alembic
(alembic 只管主库 PG)。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import DateTime, String, Text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON

_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "virtual_cases.db"
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# connect timeout 放宽,避免并发写时 database is locked。
engine = create_async_engine(
    f"sqlite+aiosqlite:///{_DB_PATH}", echo=False, connect_args={"timeout": 15}
)
VirtualSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)


class VirtualBase(DeclarativeBase):
    """预登记案件库独立的 Base,与主库 metadata 隔离。"""


class VirtualCase(VirtualBase):
    """一条预登记案件记录(内部标识沿用 virtual_case)。当事人以 JSON 数组存:

    applicants/respondents: [{"party_type": "natural"|"company", "name": str,
    "id_number": str(身份证号/统一社会信用代码), "phone": str, "address": str}]
    status: pending=待录入内网 / recorded=已录入内网;待录入的计入总览"待办案件"。
    """

    __tablename__ = "virtual_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    receipt_number: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # 预登[2026]001号
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    case_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)  # 案由
    claims: Mapped[str | None] = mapped_column(Text, nullable=True)  # 仲裁请求
    note: Mapped[str | None] = mapped_column(Text, nullable=True)  # 备注/进度
    applicants: Mapped[list] = mapped_column(JSON, default=list)
    respondents: Mapped[list] = mapped_column(JSON, default=list)
    evidences: Mapped[list] = mapped_column(JSON, default=list)  # 证据清单:[{name, content, pages}]
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


async def init_virtual_db() -> None:
    """启动时建表(幂等);老库缺列时补列(轻量迁移,不删数据)。"""
    async with engine.begin() as conn:
        await conn.run_sync(VirtualBase.metadata.create_all)
        # 2026-08-07 新增 status 列:老库补列。
        from sqlalchemy import text

        cols = (await conn.execute(text("PRAGMA table_info(virtual_cases)"))).fetchall()
        if cols and not any(c[1] == "status" for c in cols):
            await conn.execute(
                text("ALTER TABLE virtual_cases ADD COLUMN status VARCHAR(16) DEFAULT 'pending'")
            )
