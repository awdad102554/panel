"""内网开庭安排查询(近日开庭)。

数据源是内网的 getAllHoldCourt 接口(与 ../calendar 项目同一个接口),按年月查询,
返回该月全部排期。本模块负责:按"今日~下周日"过滤、跨月时合并多个月份、
从 calendar_text 里解析当事人。

不落库:开庭安排变动频繁且量小(单月个位数),每次请求实时拉取即可。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.integrations.case_system.client import CaseSystemClient, get_case_system_client

_HOLD_COURT_PATH = "/v1/api/admin/getAllHoldCourt"

# calendar_text 形如 "案号：xxx 申请人： 张三 被申请人： 某某公司 开庭时间：..."。
# 申请人用 (?<!被) 排除"被申请人",否则缺申请人时会把被申请人误当成申请人。
_APPLICANT_RE = re.compile(r"(?<!被)申请人[：:]\s*([^\s]+)")
_RESPONDENT_RE = re.compile(r"被申请人[：:]\s*([^\s]+)")


@dataclass
class Hearing:
    case_no: str
    case_id: str | None
    open_at: datetime
    end_at: datetime | None
    tribunal_name: str | None
    arbitrator: str | None
    clerk: str | None
    current_step: str | None
    applicant: str | None
    respondent: str | None


def upcoming_range(today: date | None = None) -> tuple[date, date]:
    """近日开庭的日期范围:今天 ~ 下周日(工作人员 2026-07-28 确认口径)。

    终点对齐自然周末:本周一 + 13 天 = 下周日,这样"本周剩余 + 完整下周"始终可见,
    不会像"往后固定 N 天"那样把下周切一半。
    """
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    return today, monday + timedelta(days=13)


def _parse_dt(value) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _months_between(start: date, end: date) -> list[str]:
    """范围覆盖的年月列表(接口按月查询,跨月要分别拉取)。"""
    months: list[str] = []
    cursor = start.replace(day=1)
    while cursor <= end:
        months.append(cursor.strftime("%Y-%m"))
        cursor = (cursor + timedelta(days=32)).replace(day=1)
    return months


def _to_hearing(raw: dict) -> Hearing | None:
    open_at = _parse_dt(raw.get("open_at"))
    if open_at is None:
        return None
    text = raw.get("calendar_text") or ""
    applicant = _APPLICANT_RE.search(text)
    respondent = _RESPONDENT_RE.search(text)
    case_id = raw.get("case_id")
    return Hearing(
        case_no=raw.get("case_no") or "",
        case_id=str(case_id) if case_id is not None else None,
        open_at=open_at,
        end_at=_parse_dt(raw.get("end_at")),
        tribunal_name=raw.get("tribunal_name") or None,
        arbitrator=raw.get("arbitrator") or None,
        clerk=raw.get("clerk") or None,
        current_step=raw.get("current_step") or None,
        applicant=applicant.group(1) if applicant else None,
        respondent=respondent.group(1) if respondent else None,
    )


async def fetch_hearings(
    start: date,
    end: date,
    client: CaseSystemClient | None = None,
) -> list[Hearing]:
    """拉取 [start, end] 区间内的开庭安排,按开庭时间升序。

    调用方负责捕获 CaseSystemError(内网不可用时按 0 场处理)。
    """
    client = client or get_case_system_client()
    hearings: list[Hearing] = []
    seen: set[int] = set()
    for year_month in _months_between(start, end):
        resp = await client.get(_HOLD_COURT_PATH, params={"calendar_date": year_month})
        body = resp.json() if resp.status_code == 200 else {}
        for raw in body.get("data") or []:
            # 同一排期可能在相邻月份的返回里重复出现,按内网主键去重。
            row_id = raw.get("id")
            if row_id in seen:
                continue
            hearing = _to_hearing(raw)
            if hearing is None or not (start <= hearing.open_at.date() <= end):
                continue
            seen.add(row_id)
            hearings.append(hearing)
    hearings.sort(key=lambda h: h.open_at)
    return hearings
