import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.mysql import MysqlBase


class CaseTag(MysqlBase):
    """案件标签:按案件线程(subject_key)追加,只增不改(留痕),与 InfoWeb 共用同一张表。

    subject_key 统一标识标签归属线程:
    - ext:{case_id} —— 内网案件(收件/立案/预约),同一 case_id 跨收件→立案自动衔接;
    - virt:{预登记id} —— 本地预登记案件(未落内网)。
    时间(created_at)/设备IP(client_ip)/环节(stage)/操作人(operator)由服务端自动落,
    内容(content)由用户填写;无更新/删除端点。
    """

    __tablename__ = "case_tags"

    # MySQL 无原生 UUID,存 CHAR(36) 字符串。
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    subject_key: Mapped[str] = mapped_column(String(80), index=True)  # ext:xxx / virt:xxx
    content: Mapped[str] = mapped_column(Text)  # 标签内容(用户填写)
    stage: Mapped[str] = mapped_column(String(16))  # 记录时案件所在环节(reserve/receive/handle/virtual)
    operator: Mapped[str] = mapped_column(String(64), default="")  # 操作人(IP→用户名)
    client_ip: Mapped[str] = mapped_column(String(45), default="")  # 设备IP(客户端 IP,IPv6 最长 45)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)  # 时间(UTC)
