import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.mysql import MysqlBase


class CaseTag(MysqlBase):
    """案件记事本:按案件线程(subject_key)追加,只增不改(留痕),与 InfoWeb 共用同一张表。

    subject_key 统一标识记事归属线程:
    - ext:{case_id} —— 内网案件(收件/立案/预约),同一 case_id 跨收件→立案自动衔接;
    - virt:{预登记id} —— 本地预登记案件(未落内网)。
    时间(created_at)/设备IP(client_ip)/环节(stage)/操作人(operator)由服务端自动落,
    内容(content)由用户填写;无更新/删除端点。
    """

    __tablename__ = "case_tags"

    # MySQL 无原生 UUID,存 CHAR(36) 字符串。
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    subject_key: Mapped[str] = mapped_column(String(80), index=True)  # ext:xxx / virt:xxx
    content: Mapped[str] = mapped_column(Text)  # 记事内容(用户填写)
    stage: Mapped[str] = mapped_column(String(16))  # 记录时案件所在环节(reserve/receive/pre_mediation/handle/paused/mediation/deciding/pending_hearing/pending_trial/in_progress/closed/archived/virtual)
    operator: Mapped[str] = mapped_column(String(64), default="")  # 操作人(IP→用户名)
    client_ip: Mapped[str] = mapped_column(String(45), default="")  # 设备IP(客户端 IP,IPv6 最长 45)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)  # 时间(UTC)


class CaseTagPhrase(MysqlBase):
    """记事本快捷内容:所有用户共享的常用记事短句,与 InfoWeb 共用同一张表。

    内容(content)唯一去重;创建人(operator)由客户端 IP 查 user_ip 解析,仅作展示参考。
    任何用户都可增删(共享清单),无修改(改=删旧添新)。
    """

    __tablename__ = "case_tag_phrases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content: Mapped[str] = mapped_column(String(100), unique=True)  # 快捷内容(唯一)
    operator: Mapped[str] = mapped_column(String(64), default="")  # 创建人(IP→用户名)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)  # 时间(UTC)
