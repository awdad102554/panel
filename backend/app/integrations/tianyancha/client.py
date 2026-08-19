"""天眼查 MCP 客户端(Streamable HTTP + JSON-RPC 2.0),裸 httpx 实现,零新增依赖。

天眼查 MCP 端点 https://mcp.tianyancha.com/mcp,鉴权用 API Key 请求头
`Authorization: Bearer <key>`(天眼查同时接受 `Authorization: <key>` 与
`Authorization: Bearer <key>`,这里取 Bearer 标准形式)。

Streamable HTTP 的响应体有两种:
- 普通 JSON:直接是一个 JSON-RPC 消息;
- SSE(`text/event-stream`):多个 `data:` 事件,每个是一段 JSON,按 `id` 找匹配。
会话态通过响应头 `Mcp-Session-Id` 回带(可选,服务器给了就存起来在后续请求回传)。
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# 协议版本按从新到旧尝试;服务器不支持新版本时降级重试旧版本。
_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

# 鉴权失败提示关键词(命中即视为 API Key 无效/无权限)。
_AUTH_HINTS = (
    "unauthorized",
    "forbidden",
    "invalid api key",
    "invalid key",
    "api key",
    "鉴权",
    "认证",
    "密钥",
    "授权",
    "无权限",
    "token",
)


def _looks_auth_error(message: str) -> bool:
    low = (message or "").lower()
    return any(h in low for h in _AUTH_HINTS)


class TianyanchaError(Exception):
    """天眼查 MCP 不可用(未配置/网络失败/JSON-RPC 错误/协议不兼容)。

    上层捕获后应向调用方返回 404/502 友好提示,不应抛 500。
    """


class TianyanchaAuthError(TianyanchaError):
    """天眼查鉴权失败(API Key 无效/无权限)。上层应返回 401 提示重新配置。"""


def _truncate(text: str, limit: int = 300) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _parse_sse_messages(text: str) -> list[dict]:
    """解析 SSE 文本流,返回所有 `data:` 段解析出的 JSON 对象(按事件顺序)。

    SSE 事件以空行分隔,`data:` 行可多行(按规范以 `\\n` 拼接);`event:`/`id:`/
    `:` 注释行忽略。单个 data 段解析失败则跳过该段,不影响其它段。
    """
    messages: list[dict] = []
    data_lines: list[str] = []

    def _flush() -> None:
        if not data_lines:
            return
        payload = "\n".join(data_lines)
        data_lines.clear()
        try:
            obj = json.loads(payload)
        except (ValueError, TypeError):
            return
        if isinstance(obj, dict):
            messages.append(obj)

    for line in text.splitlines():
        if line == "":
            _flush()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    _flush()
    return messages


class TianyanchaMCPClient:
    """天眼查 MCP 客户端(单例,见 get_tianyancha_client)。"""

    def __init__(self, base_url: str, api_key: str, timeout: int) -> None:
        self._base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._timeout = timeout

        self._session_id: str | None = None
        self._tools: list[dict] | None = None
        self._server_info: dict | None = None
        self._initialized = False
        self._id = 0
        self._client = httpx.AsyncClient(timeout=self._timeout)

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    @staticmethod
    def _result_or_raise(msg: dict):
        if msg.get("error"):
            err = msg["error"]
            code = err.get("code") if isinstance(err, dict) else "?"
            message = err.get("message") if isinstance(err, dict) else str(err)
            if code in (401, 403) or _looks_auth_error(message):
                raise TianyanchaAuthError(f"rpc_error[{code}]: {message}")
            raise TianyanchaError(f"rpc_error[{code}]: {message}")
        if "result" not in msg:
            raise TianyanchaError("rpc_missing_result")
        return msg["result"]

    async def _rpc(self, method: str, params: dict | None = None, *, notify: bool = False):
        """发一个 JSON-RPC 请求并返回 result;notify 无 id、不等待响应。"""
        req_id = None if notify else self._next_id()
        payload: dict = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if req_id is not None:
            payload["id"] = req_id

        try:
            resp = await self._client.post(
                self._base_url, headers=self._headers(), json=payload
            )
        except httpx.HTTPError as exc:
            raise TianyanchaError(f"rpc_network: {exc}") from exc

        sid = resp.headers.get("Mcp-Session-Id") or resp.headers.get("mcp-session-id")
        if sid:
            self._session_id = sid

        if resp.status_code in (401, 403):
            raise TianyanchaAuthError(f"rpc_http_{resp.status_code}")
        if resp.status_code != 200:
            raise TianyanchaError(f"rpc_http_{resp.status_code}: {_truncate(resp.text)}")
        if notify:
            return None

        content_type = resp.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            messages = _parse_sse_messages(resp.text)
        else:
            try:
                body = resp.json()
            except ValueError as exc:
                raise TianyanchaError(f"rpc_bad_json: {_truncate(resp.text)}") from exc
            messages = [body] if isinstance(body, dict) else []

        for msg in messages:
            if isinstance(msg, dict) and msg.get("id") == req_id:
                return self._result_or_raise(msg)
        raise TianyanchaError(f"rpc_no_matching_response: id={req_id}")

    async def initialize(self) -> dict:
        """握手拿 serverInfo 与协商协议版本;版本不兼容时降级重试。"""
        if self._initialized:
            return self._server_info or {}

        last_err: TianyanchaError | None = None
        for ver in _PROTOCOL_VERSIONS:
            try:
                result = await self._rpc(
                    "initialize",
                    {
                        "protocolVersion": ver,
                        "capabilities": {},
                        "clientInfo": {"name": "panel-backend", "version": "1.0.0"},
                    },
                )
            except TianyanchaError as exc:
                last_err = exc
                continue
            self._server_info = result if isinstance(result, dict) else {}
            self._initialized = True
            # 初始化完成通知;失败不影响后续调用(部分服务器不接受该通知)。
            try:
                await self._rpc("notifications/initialized", {}, notify=True)
            except TianyanchaError:
                pass
            logger.info("天眼查 MCP 初始化成功: %s", self._server_info.get("serverInfo"))
            return self._server_info
        raise TianyanchaError(f"initialize_failed: {last_err}")

    async def list_tools(self) -> list[dict]:
        """列出可用工具(进程内幂等缓存);每项含 name/description/inputSchema。"""
        if self._tools is not None:
            return self._tools
        await self.initialize()
        result = await self._rpc("tools/list", {})
        tools = result.get("tools") if isinstance(result, dict) else None
        self._tools = [t for t in (tools or []) if isinstance(t, dict) and t.get("name")]
        return self._tools

    async def call_tool(self, name: str, arguments: dict) -> dict:
        """调用工具,返回 MCP 的 result(content 数组 / structuredContent / isError)。"""
        await self.initialize()
        result = await self._rpc("tools/call", {"name": name, "arguments": arguments})
        return result if isinstance(result, dict) else {}

    async def aclose(self) -> None:
        """关闭底层 httpx 连接池(重建客户端时调用,避免连接泄漏)。"""
        await self._client.aclose()


_client_instance: TianyanchaMCPClient | None = None


def _close_in_background(client: TianyanchaMCPClient) -> None:
    """在运行中的事件循环里异步关闭旧客户端;无 loop(非异步上下文)则交给 GC。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(client.aclose())


def get_tianyancha_client(api_key: str | None = None) -> TianyanchaMCPClient | None:
    """获取天眼查 MCP 客户端单例;未启用或未配 API Key 时返回 None(调用方回"未配置")。

    api_key 传当前生效的 key(DB 覆盖优先,见 services/tianyancha_settings);不传时
    回落 .env。key 变化时重建客户端,内部的工具/会话缓存随之作废。
    """
    global _client_instance
    settings = get_settings()
    key = api_key if api_key is not None else settings.tianyancha_api_key
    if not settings.tianyancha_enabled or not key:
        return None
    if _client_instance is None or _client_instance.api_key != key:
        if _client_instance is not None:
            _close_in_background(_client_instance)
        _client_instance = TianyanchaMCPClient(
            settings.tianyancha_base_url, key, settings.tianyancha_timeout
        )
    return _client_instance
