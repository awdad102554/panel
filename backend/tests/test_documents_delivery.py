"""文书/送达创建的归属校验(API 层,真实库,写完清理)。

- 案件不存在时创建文书/送达返回 404(此前直接落库,孤儿记录);
- 送达带 document_id 时校验文书属于本案,不属于返回 400。
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user
from app.db.session import SessionLocal, engine
from app.main import app
from app.models.case import Case
from app.models.document import Document, DocumentType
from app.models.user import Role, User


@pytest.fixture(autouse=True)
async def _dispose_engine():
    """模块级 engine 的连接池会跨测试复用,而 pytest-asyncio 每个测试一个事件循环,
    上个循环里建的连接在新循环关闭会 RuntimeError: Event loop is closed。
    每个测试结束后在当前循环里 dispose 掉池内连接。"""
    yield
    await engine.dispose()


@pytest.fixture
async def client():
    # 显式用仲裁员角色覆盖(与免登录默认用户同角色,写接口需要 EDIT/DOCUMENT_GENERATE
    # 权限;默认用户 2026-08-12 起已改为仲裁员,此覆盖仅起显式声明作用)。
    app.dependency_overrides[get_current_user] = lambda: User(
        username="tester", display_name="测试", hashed_password="", role=Role.ARBITRATOR
    )
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.clear()


async def test_create_document_case_not_found(client: AsyncClient) -> None:
    response = await client.post(
        f"/api/v1/cases/{uuid.uuid4()}/documents", json={"doc_type": "notice"}
    )
    assert response.status_code == 404


async def test_create_service_delivery_case_not_found(client: AsyncClient) -> None:
    response = await client.post(
        f"/api/v1/cases/{uuid.uuid4()}/service-deliveries", json={"method": "mail"}
    )
    assert response.status_code == 404


async def test_create_service_delivery_document_of_other_case(client: AsyncClient) -> None:
    """文书存在但属于另一个案件 → 400,不允许跨案关联送达。"""
    case_a = Case(claims="测试案件A")
    case_b = Case(claims="测试案件B")
    async with SessionLocal() as db:
        db.add_all([case_a, case_b])
        await db.flush()
        document = Document(case_id=case_b.id, doc_type=DocumentType.NOTICE, content="测试")
        db.add(document)
        await db.commit()
        case_a_id, document_id = case_a.id, document.id
    try:
        response = await client.post(
            f"/api/v1/cases/{case_a_id}/service-deliveries",
            json={"method": "mail", "document_id": str(document_id)},
        )
        assert response.status_code == 400
    finally:
        async with SessionLocal() as db:
            doc = await db.get(Document, document_id)
            if doc is not None:
                await db.delete(doc)
            for cid in (case_a_id, case_b.id):
                case = await db.get(Case, cid)
                if case is not None:
                    await db.delete(case)
            await db.commit()


async def test_verify_reports_limit_negative_rejected(client: AsyncClient) -> None:
    """limit 有下限:负数此前直达 PostgreSQL 报 500,现在参数校验 422。"""
    response = await client.get("/api/v1/internal-cases/verify-reports", params={"limit": -1})
    assert response.status_code == 422
