from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.mysql import MysqlBase


class UserIpBinding(MysqlBase):
    """IP→用户名绑定(与 InfoWeb 共用):记录哪个设备 IP 对应哪个名字。

    两项目都按客户端 IP(nginx X-Real-IP,即真实 $remote_addr)查这张表解析操作人;
    未绑定 IP 首次使用时提示输入名字并绑定,点击右上角用户名可改名。
    """

    __tablename__ = "user_ip"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ip: Mapped[str] = mapped_column(String(45), unique=True, index=True)  # 设备IP(IPv6 最长 45)
    username: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
