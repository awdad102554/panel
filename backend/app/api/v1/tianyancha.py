"""天眼查路由:查企业基本信息 + API Key 配置(经 MCP 客户端)。"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.integrations.tianyancha.client import (
    TianyanchaAuthError,
    TianyanchaError,
    get_tianyancha_client,
)
from app.models.user import User
from app.services.tianyancha_lookup import get_company_details, search_company
from app.services.tianyancha_settings import (
    describe_tianyancha_config,
    get_tianyancha_api_key,
    save_tianyancha_api_key,
)

router = APIRouter(prefix="/tianyancha", tags=["tianyancha"])

logger = logging.getLogger(__name__)


class TianyanchaConfigUpdate(BaseModel):
    api_key: str


def _config_payload(config: dict) -> dict:
    return {
        "configured": config["configured"],
        "api_key_masked": config["api_key_masked"],
        "source": config["source"],
    }


@router.get("/config")
async def read_config(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> dict:
    config = await describe_tianyancha_config(db)
    return {"code": 200, "data": _config_payload(config)}


@router.put("/config")
async def update_config(
    payload: TianyanchaConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> dict:
    try:
        await save_tianyancha_api_key(db, payload.api_key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await db.commit()
    config = await describe_tianyancha_config(db)
    return {"code": 200, "data": _config_payload(config)}


@router.get("/lookup/company")
async def lookup_company_endpoint(
    name: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> dict:
    """查企业基本信息(企业名称/统一社会信用代码 → 工商信息)。"""
    client = get_tianyancha_client(api_key=await get_tianyancha_api_key(db))
    if client is None:
        raise HTTPException(
            status_code=404,
            detail="天眼查未配置,请在「天眼查」页配置 API Key 或 backend/.env 配置 TIANYANCHA_API_KEY",
        )
    try:
        data = await search_company(name, client=client)
    except TianyanchaAuthError as exc:
        logger.warning("天眼查鉴权失败: %s", exc)
        raise HTTPException(
            status_code=401, detail="天眼查 API Key 无效或无权限，请重新配置"
        ) from exc
    except TianyanchaError as exc:
        logger.warning("天眼查查询异常: %s", exc)
        raise HTTPException(status_code=502, detail="天眼查查询服务不可用") from exc
    if not data.get("fields"):
        raise HTTPException(status_code=404, detail="未查到匹配的企业信息")
    return {"code": 200, "data": data}


@router.get("/lookup/details")
async def lookup_details_endpoint(
    name: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> dict:
    """查企业基础详情(工商登记/联系方式/简介等),按需调用基础画像工具。"""
    client = get_tianyancha_client(api_key=await get_tianyancha_api_key(db))
    if client is None:
        raise HTTPException(
            status_code=404,
            detail="天眼查未配置,请在「天眼查」页配置 API Key 或 backend/.env 配置 TIANYANCHA_API_KEY",
        )
    try:
        data = await get_company_details(name, client=client)
    except TianyanchaAuthError as exc:
        logger.warning("天眼查鉴权失败: %s", exc)
        raise HTTPException(
            status_code=401, detail="天眼查 API Key 无效或无权限，请重新配置"
        ) from exc
    except TianyanchaError as exc:
        logger.warning("天眼查详情查询异常: %s", exc)
        raise HTTPException(status_code=502, detail="天眼查查询服务不可用") from exc
    if not data.get("overview") and not data.get("details") and not data.get("raw"):
        raise HTTPException(status_code=404, detail="未查到企业详情")
    return {"code": 200, "data": data}


@router.get("/tools")
async def list_tools_endpoint(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> dict:
    """列出天眼查 MCP 当前可用工具(调试辅助,用于确认真实工具名)。"""
    client = get_tianyancha_client(api_key=await get_tianyancha_api_key(db))
    if client is None:
        raise HTTPException(
            status_code=404,
            detail="天眼查未配置,请在「天眼查」页配置 API Key 或 backend/.env 配置 TIANYANCHA_API_KEY",
        )
    try:
        tools = await client.list_tools()
    except TianyanchaAuthError as exc:
        logger.warning("天眼查鉴权失败: %s", exc)
        raise HTTPException(
            status_code=401, detail="天眼查 API Key 无效或无权限，请重新配置"
        ) from exc
    except TianyanchaError as exc:
        logger.warning("天眼查工具列表异常: %s", exc)
        raise HTTPException(status_code=502, detail="天眼查查询服务不可用") from exc
    return {
        "code": 200,
        "data": [
            {"name": t.get("name"), "description": t.get("description")}
            for t in tools
        ],
    }
