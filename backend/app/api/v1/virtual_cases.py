"""预登记案件路由:本地 SQLite 存取 + 查人/查企(直连内网数据共享接口)。

数据存 backend/data/virtual_cases.db(与主库分离,不落内网)。
查自然人/查企业见 services/datashare_lookup.py——直连内网案件系统同主机的
数据共享代理接口,认证复用 CaseSystemClient,不依赖 InfoWeb 在线。
"""

import logging
import tempfile
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_user
from app.db.virtual import VirtualCase, VirtualSessionLocal
from app.integrations.case_system.client import CaseSystemError
from app.models.user import User
from app.services.application_doc import generate_application
from app.services.datashare_lookup import lookup_company, lookup_person

router = APIRouter(prefix="/virtual-cases", tags=["virtual-cases"])

logger = logging.getLogger(__name__)


_PARTY_TYPES = ("natural", "company")


class PartyIn(BaseModel):
    """当事人。字段与 InfoWeb 新建案件表单对齐:
    自然人用 name/gender/ethnicity/birth_date/id_number/address/phone 等;
    公司用 name/id_number(统一社会信用代码)/address/phone/legal_person/legal_title。
    申请人每人可带独立 claims(仲裁请求)/facts(事实理由)。"""

    party_type: str = "natural"  # natural=自然人 / company=公司
    name: str
    id_number: str | None = None  # 身份证号 / 统一社会信用代码
    gender: str | None = None
    ethnicity: str | None = None  # 民族
    birth_date: str | None = None
    address: str | None = None
    phone: str | None = None
    work_place: str | None = None  # 工作地点(公司)
    position: str | None = None  # 岗位
    entry_date: str | None = None  # 入职时间
    monthly_wage: str | None = None  # 月工资
    claims: str | None = None  # 旧版单一仲裁请求文本(兼容);新表单用 requests
    requests: list[str] = []  # 仲裁请求列表(申请人,每人可多条,可增删行)
    facts: str | None = None  # 事实与理由(申请人,每人一条)
    legal_person: str | None = None  # 法定代表人(公司)
    legal_title: str | None = None  # 职务(公司)


class EvidenceIn(BaseModel):
    name: str
    content: str | None = None  # 证明内容
    pages: str | None = None  # 页码/份数


class VirtualCaseIn(BaseModel):
    case_reason: str | None = None
    claims: str | None = None  # 兼容旧结构的顶层仲裁请求,新表单用申请人各自的 claims
    note: str | None = None
    applicants: list[PartyIn] = Field(min_length=1)
    respondents: list[PartyIn] = Field(min_length=1)
    evidences: list[EvidenceIn] = []


class VirtualCaseOut(BaseModel):
    id: str
    receipt_number: str
    status: str  # pending=待录入内网 / recorded=已录入
    case_reason: str | None
    claims: str | None
    note: str | None
    applicants: list[PartyIn]
    respondents: list[PartyIn]
    evidences: list[EvidenceIn] = []
    created_by: str
    created_at: datetime
    updated_at: datetime


def _parse_parties(items: list | None) -> list[PartyIn]:
    """逐条解析当事人 JSON;单条脏数据跳过并记日志,不让整条案件(乃至整个列表)500。"""
    out: list[PartyIn] = []
    for p in items or []:
        if not isinstance(p, dict) or not p.get("name"):
            continue
        try:
            out.append(PartyIn(**p))
        except ValidationError:
            logger.warning("预登记当事人数据异常,已跳过: %s", p.get("name"))
    return out


def _parse_evidences(items: list | None) -> list[EvidenceIn]:
    out: list[EvidenceIn] = []
    for e in items or []:
        if not isinstance(e, dict) or not e.get("name"):
            continue
        try:
            out.append(EvidenceIn(**e))
        except ValidationError:
            logger.warning("预登记证据数据异常,已跳过: %s", e.get("name"))
    return out


def _to_out(row: VirtualCase) -> VirtualCaseOut:
    return VirtualCaseOut(
        id=row.id,
        receipt_number=row.receipt_number,
        status=row.status,
        case_reason=row.case_reason,
        claims=row.claims,
        note=row.note,
        applicants=_parse_parties(row.applicants),
        respondents=_parse_parties(row.respondents),
        evidences=_parse_evidences(row.evidences),
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _validate_parties(payload: VirtualCaseIn) -> None:
    for party in (*payload.applicants, *payload.respondents):
        if party.party_type not in _PARTY_TYPES:
            raise HTTPException(status_code=422, detail=f"当事人类型不合法: {party.party_type}")
        if not party.name.strip():
            raise HTTPException(status_code=422, detail="当事人姓名/名称不能为空")


async def _next_receipt_number(db) -> str:
    """预登[YYYY]NNN号:取当年最大序号 +1(不用 count,删除中间编号后也不会撞号)。"""
    year = datetime.now().year
    prefix = f"预登[{year}]"
    rows = (
        await db.execute(
            select(VirtualCase.receipt_number).where(
                VirtualCase.receipt_number.like(f"{prefix}%")
            )
        )
    ).scalars().all()
    max_seq = 0
    for rn in rows:
        try:
            seq = int(rn.removeprefix(prefix).removesuffix("号"))
            max_seq = max(max_seq, seq)
        except ValueError:
            continue
    return f"{prefix}{max_seq + 1:03d}号"


@router.get("", response_model=list[VirtualCaseOut])
async def list_virtual_cases(
    _current_user: User = Depends(get_current_user),
) -> list[VirtualCaseOut]:
    async with VirtualSessionLocal() as db:
        rows = (
            await db.execute(select(VirtualCase).order_by(VirtualCase.created_at.desc()))
        ).scalars().all()
        return [_to_out(r) for r in rows]


@router.post("", response_model=VirtualCaseOut)
async def create_virtual_case(
    payload: VirtualCaseIn,
    current_user: User = Depends(get_current_user),
) -> VirtualCaseOut:
    _validate_parties(payload)
    async with VirtualSessionLocal() as db:
        row = VirtualCase(
            receipt_number=await _next_receipt_number(db),
            case_reason=payload.case_reason,
            claims=payload.claims,
            note=payload.note,
            applicants=[p.model_dump() for p in payload.applicants],
            respondents=[p.model_dump() for p in payload.respondents],
            evidences=[e.model_dump() for e in payload.evidences],
            created_by=current_user.username,
        )
        db.add(row)
        # 并发撞号兜底:回滚后重新取号再试,最多 3 次(此前只重试一次,极端并发仍可能 500)。
        for attempt in range(3):
            try:
                await db.commit()
                break
            except IntegrityError:
                await db.rollback()
                if attempt == 2:
                    raise HTTPException(status_code=500, detail="预登记编号生成冲突,请重试")
                row.receipt_number = await _next_receipt_number(db)
                db.add(row)
        return _to_out(row)


@router.put("/{case_id}", response_model=VirtualCaseOut)
async def update_virtual_case(
    case_id: str,
    payload: VirtualCaseIn,
    _current_user: User = Depends(get_current_user),
) -> VirtualCaseOut:
    _validate_parties(payload)
    async with VirtualSessionLocal() as db:
        row = await db.get(VirtualCase, case_id)
        if row is None:
            raise HTTPException(status_code=404, detail="预登记案件不存在")
        row.case_reason = payload.case_reason
        row.claims = payload.claims
        row.note = payload.note
        row.applicants = [p.model_dump() for p in payload.applicants]
        row.respondents = [p.model_dump() for p in payload.respondents]
        row.evidences = [e.model_dump() for e in payload.evidences]
        await db.commit()
        return _to_out(row)


@router.delete("/{case_id}", status_code=204)
async def delete_virtual_case(
    case_id: str,
    _current_user: User = Depends(get_current_user),
) -> None:
    async with VirtualSessionLocal() as db:
        row = await db.get(VirtualCase, case_id)
        if row is None:
            raise HTTPException(status_code=404, detail="预登记案件不存在")
        await db.delete(row)
        await db.commit()


class StatusUpdate(BaseModel):
    status: str  # recorded / pending


@router.put("/{case_id}/status", response_model=VirtualCaseOut)
async def update_virtual_case_status(
    case_id: str,
    payload: StatusUpdate,
    _current_user: User = Depends(get_current_user),
) -> VirtualCaseOut:
    """标记已录入内网 / 恢复待录入。"""
    if payload.status not in ("pending", "recorded"):
        raise HTTPException(status_code=422, detail="status 只能是 pending 或 recorded")
    async with VirtualSessionLocal() as db:
        row = await db.get(VirtualCase, case_id)
        if row is None:
            raise HTTPException(status_code=404, detail="预登记案件不存在")
        row.status = payload.status
        await db.commit()
        return _to_out(row)


async def list_pending_virtual_cases() -> list[VirtualCase]:
    """待录入内网的预登记案件(供总览"待办案件"卡片计数/明细)。"""
    async with VirtualSessionLocal() as db:
        rows = (
            await db.execute(
                select(VirtualCase).where(VirtualCase.status == "pending")
            )
        ).scalars().all()
        return list(rows)


@router.get("/{case_id}/application")
async def download_application(
    case_id: str,
    _current_user: User = Depends(get_current_user),
) -> FileResponse:
    """生成并下载该预登记案件的仲裁申请书(docx,格式与 InfoWeb 一致)。

    生成写临时文件(唯一名,避免并发同路径写坏),下载完成后后台删除,不堆积。
    """
    async with VirtualSessionLocal() as db:
        row = await db.get(VirtualCase, case_id)
        if row is None:
            raise HTTPException(status_code=404, detail="预登记案件不存在")
        applicants = [p for p in (row.applicants or []) if isinstance(p, dict) and p.get("name")]
        respondents = [p for p in (row.respondents or []) if isinstance(p, dict) and p.get("name")]
        if not applicants or not respondents:
            raise HTTPException(status_code=422, detail="请先完善申请人和被申请人信息")

    first_name = applicants[0].get("name") or "未知"
    filename = f"仲裁申请书-{first_name}-{date.today().strftime('%Y%m%d')}.docx"
    # 同步生成挪到线程池,不阻塞事件循环。
    tmp = tempfile.NamedTemporaryFile(
        prefix="application_", suffix=".docx", delete=False, dir=tempfile.gettempdir()
    )
    tmp_path = Path(tmp.name)
    tmp.close()
    try:
        await run_in_threadpool(
            generate_application,
            {"applicants": applicants, "respondents": respondents},
            tmp_path,
        )
    except Exception:
        # 生成失败要删掉已创建的空临时文件,否则 /tmp 会缓慢堆积。
        tmp_path.unlink(missing_ok=True)
        logger.exception("生成仲裁申请书失败: %s", case_id)
        raise HTTPException(status_code=500, detail="仲裁申请书生成失败,请检查案件信息是否完整")
    return FileResponse(
        tmp_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        background=BackgroundTask(lambda: tmp_path.unlink(missing_ok=True)),
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/lookup/person")
async def lookup_person_endpoint(
    id_card: str,
    _current_user: User = Depends(get_current_user),
) -> dict:
    """查自然人(身份证→内网数据共享接口,返回内网原始字段)。"""
    try:
        data = await lookup_person(id_card)
    except CaseSystemError as exc:
        logger.warning("查自然人接口异常: %s", exc)
        raise HTTPException(status_code=502, detail="查询服务不可用") from exc
    if data is None:
        raise HTTPException(status_code=404, detail="未查到该身份证对应的自然人信息")
    return {"code": 200, "data": data}


@router.get("/lookup/company")
async def lookup_company_endpoint(
    name: str,
    _current_user: User = Depends(get_current_user),
) -> dict:
    """查企业(名称模糊匹配,返回中文字段列表)。"""
    try:
        items = await lookup_company(name)
    except CaseSystemError as exc:
        logger.warning("查企业接口异常: %s", exc)
        raise HTTPException(status_code=502, detail="查询服务不可用") from exc
    if not items:
        raise HTTPException(status_code=404, detail="未查到匹配的企业信息")
    return {"code": 200, "data": items}
