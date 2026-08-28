"""企业委托代理人绑定记录。

记录历年公司主体（主要是被申请人，也包括申请人为公司时）的委托代理人信息，
用于查询某公司历年用过哪些代理人，以及某代理人代理过哪些案件。

数据来源：internal_case_trackings.raw_payload 中的 respondent_arr/applicant_arr
每个当事人的 agents 数组。每次轻量同步后增量更新。
"""

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class CompanyAgentBinding(Base):
    """企业-代理人绑定记录（一案一条，历史留痕）。"""

    __tablename__ = "company_agent_bindings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 企业信息
    company_name: Mapped[str] = mapped_column(String(255), index=True)  # 企业名称
    company_credit_code: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 统一社会信用代码

    # 代理人信息
    agent_name: Mapped[str] = mapped_column(String(64), index=True)  # 代理人姓名
    agent_type: Mapped[int] = mapped_column(Integer)  # 代理人类型码（1法定/2指定/3近亲属/4团体推荐/5单位工作人员/6律师/7法律服务工作者）
    agent_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 联系电话
    agent_law_firm: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 律所名称（仅律师类）
    agent_id_number: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 身份证号/证件号

    # 关联案件信息
    party_role: Mapped[str] = mapped_column(String(16))  # 当事人角色（applicant/respondent）
    external_case_id: Mapped[str] = mapped_column(String(64), index=True)  # 内网案件ID
    case_no: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 案号
    filed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)  # 立案时间（用于排序）

    # 元数据
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # 唯一约束：同一公司、同一代理人、同一案件只记录一次
    __table_args__ = (
        UniqueConstraint("company_name", "agent_name", "external_case_id", name="uk_company_agent_case"),
        Index("idx_filed_at_desc", filed_at.desc()),  # 用于按时间倒序查询
    )
