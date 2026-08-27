import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class InternalStage(str, enum.Enum):
    """内网案件所在环节。取值对应内网 3 个真实接口 arb/{reserve,receive,handle}。

    VIRTUAL 是面板本地预登记案件(不来自内网),仅用于总览"待办案件"明细展示。
    """

    RESERVE = "reserve"  # 线上预约/预申请
    RECEIVE = "receive"  # 收件审查
    HANDLE = "handle"  # 立案在办(含开庭、中止、裁决、结案,靠 current_step 区分子状态)
    VIRTUAL = "virtual"  # 本地预登记(不落内网)


class InternalCaseTracking(Base):
    """内网案件同步快照,按 external_case_id(内网 case_id)全量 upsert。

    数据源是内网案件系统(10.96.10.78:8080)的 arb/{reserve,receive,handle} 三个环节接口,
    由后台定时任务(app.services.internal_case_sync)拉取。注意:receive/reserve 接口返回的是
    未过滤列表(不是"当前仍停留在该环节"的过滤列表;reserve 审核通过即离开列表,只留
    待审核/退回补正记录),因此同一个 case_id 可能同时
    出现在 receive 和 handle 里;同步按 reserve→receive→handle 顺序 upsert,后写的 handle 覆盖前者,
    最终 stage 反映案件真实所处的最靠后环节。
    """

    __tablename__ = "internal_case_trackings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_case_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # 内网 case_id
    stage: Mapped[InternalStage] = mapped_column(String(16), index=True)
    current_step: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 仅 handle 阶段有意义
    case_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False)  # handle.stop == 1(审理中止)
    # 剩余天数(负数=已超期)。handle: closing_time_limit;reserve: -overdue_days;receive: None。
    native_remaining_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_way: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 累计中止天数(来自内网 caseData 的 review_matter 中止/恢复审理记录配对),用于从
    # 审理时长中扣除中止期间。None = 尚未回填;已结案案件只取一次,在办案件随
    # 后台任务每轮重算(暂停仍在累计),结案时由 sync 置回 None 触发按结案日重算。
    paused_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 最近一次审限重新计算的日期(变更/增加仲裁请求、仲裁反申请、追加当事人被受理后,
    # 仲裁期限依法重新起算);来自 review_matter,与 paused_days 同批回填。
    # None = 无重启记录(或尚未回填),审限从立案日起算。
    clock_reset_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    # 重启日之后的中止天数(仅 clock_reset_at 非空时有意义):超审限判定从重启日起算,
    # 只能扣重启后的中止;而 paused_days 是全量中止,供立案日起算的审理时长使用。
    paused_after_reset_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 进入当前 (stage, current_step) 的锚点时间。近似值:内网不提供"进入某子状态的时刻",
    # 首见时用该环节最接近的原生时间戳兜底,之后每轮同步若发现 (stage, current_step) 变化,
    # 就更新为"发现变化的同步时刻"(非真实变化时刻,粒度取决于同步频率)。
    phase_entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw_payload: Mapped[dict] = mapped_column(JSONB)  # 内网原始记录(含嵌套 cases 详情)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CaseTimeLimitOverride(Base):
    """单个内网案件的人工时效覆盖:设了截止日期就以它为准,不再走默认阈值。"""

    __tablename__ = "case_time_limit_overrides"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_case_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    deadline_override: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SyncVerificationReport(Base):
    """一致性校验报告:全量只读对账的结果留档。

    用途不是修正数据,而是给轻量同步的排查提供历史证据——每次校验的统计数字与
    完整差异明细(缺失案件、字段不一致)都保存在 details 里,供事后分析。
    """

    __tablename__ = "sync_verification_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    checked: Mapped[int] = mapped_column(Integer)  # 本次比对内网全量案件数
    missing_total: Mapped[int] = mapped_column(Integer)  # 内网有、快照缺失件数
    mismatch_total: Mapped[int] = mapped_column(Integer)  # 字段不一致处数
    only_in_snapshot: Mapped[int] = mapped_column(Integer)  # 快照多出(内网全量未返回)
    # 完整差异明细:{"missing_in_snapshot": [...], "field_mismatches": [...]}
    details: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
