import enum
import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Role(str, enum.Enum):
    """对应 04 PRD 第二章的四类用户。"""

    ARBITRATOR = "arbitrator"  # 仲裁员
    CLERK = "clerk"  # 书记员
    MEDIATOR = "mediator"  # 调解员
    ADMIN = "admin"  # 管理员


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(64))
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(String(32))
