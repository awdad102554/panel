from datetime import datetime, timezone

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


def utcnow() -> datetime:
    """带时区的当前 UTC 时间,供 DateTime(timezone=True) 列做默认值。

    不能用 datetime.utcnow:它返回 naive datetime,与从库里读回的 aware datetime
    比较时会 TypeError,且写入 tz-aware 列时可能被驱动按本地时区解释而偏移。
    """
    return datetime.now(timezone.utc)
