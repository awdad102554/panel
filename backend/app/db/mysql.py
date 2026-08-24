"""共享 MySQL 连接(与 InfoWeb 同库,存案件标签 case_tags + IP→用户名绑定 user_ip)。

panel 主库是 PostgreSQL(asyncpg),但案件标签/IP 绑定要跟 InfoWeb 共用同一张表,
故另起一条 MySQL 异步连接。表结构由 get_mysql_engine + Base.metadata.create_all
在启动时幂等创建(InfoWeb 侧 database_schema.py 也 CREATE TABLE IF NOT EXISTS)。
"""

from __future__ import annotations

from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()


def _mysql_url() -> URL:
    # database 名是中文("判决书生成"),用 URL.create 避免手工 urlencode 出错。
    return URL.create(
        "mysql+aiomysql",
        username=settings.mysql_user,
        password=settings.mysql_password,
        host=settings.mysql_host,
        port=settings.mysql_port,
        database=settings.mysql_db,
        query={"charset": "utf8mb4"},
    )


# MySQL wait_timeout=600(10 分钟)会断开空闲连接;aiomysql 适配器的 ping(reconnect) 与
# SQLAlchemy pymysql 方言 do_ping(ping() 无参)签名不兼容,pool_pre_ping 无法开启。
# 故把 pool_recycle 设为 300(5 分钟,wait_timeout 的一半):连接在 MySQL 断开前就被
# SQLAlchemy 丢弃重建,从根上避免「空闲后首次请求 Lost connection (2013)」。
mysql_engine = create_async_engine(
    _mysql_url(), echo=False, pool_pre_ping=False, pool_recycle=300
)

MysqlSessionLocal = async_sessionmaker(bind=mysql_engine, expire_on_commit=False)


class MysqlBase(DeclarativeBase):
    """MySQL 共享表的声明基类(独立于 PG 的 app.db.base.Base)。"""


async def get_mysql_db() -> AsyncSession:
    async with MysqlSessionLocal() as session:
        yield session


async def init_mysql_db() -> None:
    """启动时幂等建 MySQL 共享表(IF NOT EXISTS 语义)。"""
    # 懒导入模型,确保它们已注册进 MysqlBase.metadata(模块级导入会造成循环依赖)。
    from app.models.case_tag import CaseTag  # noqa: F401
    from app.models.user_ip import UserIpBinding  # noqa: F401

    async with mysql_engine.begin() as conn:
        await conn.run_sync(MysqlBase.metadata.create_all)
