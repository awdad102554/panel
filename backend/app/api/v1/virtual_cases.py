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
from app.services.case_submit import (
    DuplicateCaseWarning,
    SubmitSpec,
    _fill_company_info,
    build_draft,
    build_payload,
    get_request_catalog,
    submit_case,
)
from app.services.datashare_lookup import lookup_agent, lookup_company, lookup_person

router = APIRouter(prefix="/virtual-cases", tags=["virtual-cases"])

logger = logging.getLogger(__name__)


_PARTY_TYPES = ("natural", "company")


class AgentIn(BaseModel):
    """代理人(内网代理人-添加弹窗字段,样例3):agent_type 类型码见
    case_submit.AGENT_TYPES;律师类(6/7)带律所/律师类型/委托权限/法律援助,
    法定/近亲属类带与当事人关系 relation(选"其他"时文本进 select_other_content)。"""

    name: str
    agent_type: int  # 1法定 2指定 3近亲属 4团体/单位推荐 5单位工作人员 6律师 7法律服务工作者
    id_type: str | None = None
    id_number: str | None = None
    mobile: str | None = None
    sex: str | None = None
    relation: str | None = None  # 与当事人关系
    select_other_content: str | None = None  # 关系为"其他"时的说明
    agent_auth: str | None = None  # 委托权限: 一般授权/特别授权
    law_firm_name: str | None = None  # 律师事务所名称
    lawer_type: int | None = None  # 1执业律师 2实习律师(内网字段拼写如此)
    is_legal_aid: int | None = None  # 法律援助 0/1
    lawyer_card_number: str | None = None  # 律师执业证号
    nation: str | None = None  # 民族
    birth: str | None = None  # 出生日期
    address: str | None = None  # 住址
    receive_address: str | None = None  # 送达地址
    job: str | None = None


class PartyIn(BaseModel):
    """当事人。字段与 InfoWeb 新建案件表单对齐:
    自然人用 name/gender/ethnicity/birth_date/id_number/address/phone 等;
    公司用 name/id_number(统一社会信用代码)/address/phone/legal_person/legal_title。
    申请人每人可带独立 claims(仲裁请求)/facts(事实理由);均可带 agents(代理人)。"""

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
    agents: list[AgentIn] = []  # 代理人(可多个)


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
    """逐条解析当事人 JSON;单条脏数据跳过并记日志,不让整条案件(乃至整个列表)500。

    agents 先逐条清洗:一条脏 agent 不该拖垮整个当事人(否则出现"页面看不到、
    提交(_row_to_case_dict 原始 JSON)却带上"的矛盾,自检发现 2026-08-11)。
    """
    out: list[PartyIn] = []
    for p in items or []:
        if not isinstance(p, dict) or not p.get("name"):
            continue
        p = dict(p)
        agents: list[AgentIn] = []
        for a in p.get("agents") or []:
            try:
                agents.append(AgentIn(**a))
            except (ValidationError, TypeError):
                logger.warning("预登记代理人数据异常,已跳过: %s", (a or {}).get("name") if isinstance(a, dict) else a)
        p["agents"] = agents
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
        # 并发撞号兜底:回滚后 expunge 再改号重加(rollback 后直接 add 原对象是
        # no-op,会发 UPDATE 0 行抛 StaleDataError——此前兜底路径一触发就 500),
        # 最多 3 次。
        for attempt in range(3):
            try:
                await db.commit()
                break
            except IntegrityError:
                await db.rollback()
                if attempt == 2:
                    raise HTTPException(status_code=500, detail="预登记编号生成冲突,请重试")
                db.expunge(row)
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


def _row_to_case_dict(row: VirtualCase) -> dict:
    """提交组装用的案件 dict(当事人保留原始 JSON,不做 PartyIn 过滤)。"""
    return {
        "case_reason": row.case_reason,
        "claims": row.claims,
        "applicants": row.applicants or [],
        "respondents": row.respondents or [],
    }


@router.post("/{case_id}/submit-draft")
async def submit_draft(
    case_id: str,
    _current_user: User = Depends(get_current_user),
) -> dict:
    """提交草稿:自动猜仲裁请求类型 + 查企业回填 + 校验 + 字典,供提交对话框展示。"""
    async with VirtualSessionLocal() as db:
        row = await db.get(VirtualCase, case_id)
        if row is None:
            raise HTTPException(status_code=404, detail="预登记案件不存在")
        case = _row_to_case_dict(row)
    try:
        return await build_draft(case)
    except CaseSystemError as exc:
        logger.warning("提交草稿字典拉取失败: %s", exc)
        raise HTTPException(status_code=502, detail="内网字典服务不可用,请稍后重试") from exc


@router.post("/{case_id}/submit-preview")
async def submit_preview(
    case_id: str,
    spec: SubmitSpec,
    _current_user: User = Depends(get_current_user),
) -> dict:
    """预览组装好的内网请求体(不发内网),供与抓包样例比对/提交前确认。"""
    async with VirtualSessionLocal() as db:
        row = await db.get(VirtualCase, case_id)
        if row is None:
            raise HTTPException(status_code=404, detail="预登记案件不存在")
        case = _row_to_case_dict(row)
    try:
        catalog = await get_request_catalog()
    except CaseSystemError as exc:
        logger.warning("预览字典拉取失败: %s", exc)
        raise HTTPException(status_code=502, detail="内网字典服务不可用,请稍后重试") from exc
    applicants = [dict(p) for p in case["applicants"]]
    respondents = [dict(p) for p in case["respondents"]]
    # 与正式提交一致:预览也做企业信息回填。
    await _fill_company_info(applicants, respondents)
    case = {**case, "applicants": applicants, "respondents": respondents}
    try:
        return build_payload(case, spec, catalog)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("预览请求体组装失败[%s]", case_id)
        raise HTTPException(status_code=422, detail=f"请求体组装失败: {exc}") from exc


@router.post("/{case_id}/submit")
async def submit_to_internal(
    case_id: str,
    spec: SubmitSpec,
    _current_user: User = Depends(get_current_user),
) -> dict:
    """正式提交到内网收件(receive/add);成功后预登记置为 recorded。

    事务与网络调用分离:先读案件关 session 再提交内网(避免持库等网络放大
    SQLite locked),内网成功后再开新 session 落状态;状态落库失败不影响已建案
    事实,返回 warning 让前端提示人工核对(自检发现 2026-08-11)。
    """
    async with VirtualSessionLocal() as db:
        row = await db.get(VirtualCase, case_id)
        if row is None:
            raise HTTPException(status_code=404, detail="预登记案件不存在")
        if row.status == "recorded":
            raise HTTPException(status_code=409, detail="该案件已录入内网,请勿重复提交")
        case = _row_to_case_dict(row)
        receipt_number = row.receipt_number
    try:
        data = await submit_case(case, spec)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DuplicateCaseWarning as exc:
        # 内网提示疑似重复案件:返回 409,前端弹确认后带 force=true 重试。
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CaseSystemError as exc:
        logger.warning("提交内网收件失败[%s]: %s", receipt_number, exc)
        message = str(exc)
        # 网络层失败(超时/不可达)时请求可能已到内网并建案,不能笼统报失败。
        if "request_failed" in message or "retry_failed" in message:
            message = "内网响应异常,提交结果未知——请先到内网收件列表核实是否已生成,避免重复提交"
        raise HTTPException(status_code=502, detail=message) from exc

    warning = None
    try:
        async with VirtualSessionLocal() as db:
            row = await db.get(VirtualCase, case_id)
            row.status = "recorded"
            row.note = (row.note or "") + f" [已提交内网收件 {datetime.now():%Y-%m-%d %H:%M}]"
            await db.commit()
    except Exception:
        logger.exception("内网已建案但预登记状态更新失败[%s]: %s", receipt_number, data)
        warning = "内网已生成收件,但本地状态更新失败,请人工核对后标记已录入"
    return {"code": 200, "data": data, "warning": warning}


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


@router.get("/lookup/agent")
async def lookup_agent_endpoint(
    name: str | None = None,
    id_number: str | None = None,
    mobile: str | None = None,
    _current_user: User = Depends(get_current_user),
) -> dict:
    """查代理人(内网 cases/Agent:姓名/身份证号/手机号至少一项,返回内网原始记录列表)。"""
    try:
        items = await lookup_agent(name=name, id_number=id_number, mobile=mobile)
    except CaseSystemError as exc:
        logger.warning("查代理人接口异常: %s", exc)
        raise HTTPException(status_code=502, detail="查询服务不可用") from exc
    if not items:
        raise HTTPException(status_code=404, detail="未查到匹配的代理人信息")
    return {"code": 200, "data": items}


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
