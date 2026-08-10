"""内网案件系统(10.96.10.78:8080)HTTP 客户端。

复用 InfoWeb 的账号与登录流程(见 InfoWeb modules/login_manager.py、
services/external_api.py):POST 登录拿 authKey/sessionId,后续请求带这两个头,
遇 401 清缓存重登重试一次。这里用 httpx.AsyncClient 实现异步版,token 仅内存缓存。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# 固定请求头,与 InfoWeb modules/config.py 的 DEFAULT_HEADERS 一致。
_DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "Content-Type": "application/json;charset=UTF-8",
    "Host": "10.96.10.78:8080",
    "Origin": "http://10.96.10.78",
    "Referer": "http://10.96.10.78/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/80.0.3987.122 Safari/537.36 Edg/80.0.361.62"
    ),
}


class CaseSystemError(Exception):
    """内网案件系统不可用(登录失败/超时/网络不可达/认证失效)。

    上层捕获后应回退到本地统计,不应向调用方抛 500。
    """


class CaseSystemClient:
    """内网案件系统客户端(单例,见 get_case_system_client)。"""

    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.case_system_base_url.rstrip("/")
        self._username = settings.case_system_username
        self._password = settings.case_system_password
        self._timeout = settings.case_system_timeout
        self._session_hours = settings.case_system_session_hours

        self._auth_key: str | None = None
        self._session_id: str | None = None
        self._expiry: datetime | None = None
        self._lock = asyncio.Lock()
        self._client = httpx.AsyncClient(timeout=self._timeout)

    def _token_valid(self) -> bool:
        return bool(
            self._auth_key
            and self._session_id
            and self._expiry
            and datetime.utcnow() < self._expiry
        )

    async def login(self, *, force: bool = False) -> None:
        """登录内网系统,拿 authKey/sessionId 写入内存缓存。

        并发下用锁串行化,避免多个请求同时触发重复登录。
        """
        async with self._lock:
            if not force and self._token_valid():
                return

            url = f"{self._base_url}/v1/api/admin/login"
            payload = {"username": self._username, "password": self._password}
            try:
                resp = await self._client.post(
                    url, headers=_DEFAULT_HEADERS, json=payload
                )
                resp.raise_for_status()
                body = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise CaseSystemError(f"login_request_failed: {exc}") from exc

            if body.get("code") != 200:
                raise CaseSystemError(
                    f"login_rejected: {body.get('message', 'unknown')}"
                )

            data = body.get("data") or {}
            auth_key = data.get("authKey")
            session_id = data.get("sessionId")
            if not auth_key or not session_id:
                raise CaseSystemError("login_missing_credentials")

            self._auth_key = auth_key
            self._session_id = session_id
            self._expiry = datetime.utcnow() + timedelta(hours=self._session_hours)
            logger.info("内网案件系统登录成功: %s", self._username)

    def _auth_headers(self) -> dict[str, str]:
        headers = dict(_DEFAULT_HEADERS)
        headers["authKey"] = self._auth_key or ""
        headers["sessionId"] = self._session_id or ""
        return headers

    async def request(
        self, method: str, path: str, *, retry_on_401: bool = True, **kwargs
    ) -> httpx.Response:
        """带认证发一次请求;遇 401 清缓存重登并重试一次(仿 request_with_auth)。"""
        if not self._token_valid():
            await self.login()

        url = f"{self._base_url}{path}"
        try:
            resp = await self._client.request(
                method, url, headers=self._auth_headers(), **kwargs
            )
        except httpx.HTTPError as exc:
            raise CaseSystemError(f"request_failed: {exc}") from exc

        if resp.status_code != 401 or not retry_on_401:
            return resp

        logger.warning("内网案件系统返回 401,重新登录后重试...")
        self._auth_key = None
        self._session_id = None
        await self.login(force=True)
        try:
            return await self._client.request(
                method, url, headers=self._auth_headers(), **kwargs
            )
        except httpx.HTTPError as exc:
            raise CaseSystemError(f"retry_failed: {exc}") from exc

    async def get(self, path: str, **kwargs) -> httpx.Response:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs) -> httpx.Response:
        return await self.request("POST", path, **kwargs)


_client_instance: CaseSystemClient | None = None


def get_case_system_client() -> CaseSystemClient:
    """获取内网案件系统客户端单例,复用同一 AsyncClient 连接池。"""
    global _client_instance
    if _client_instance is None:
        _client_instance = CaseSystemClient()
    return _client_instance
