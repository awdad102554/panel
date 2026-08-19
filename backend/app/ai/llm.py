"""真实 LLM Provider 调用(OpenAI 兼容 /chat/completions)。

与 app/ai/client.py 的 MockLLMClient 分开:后者是案件工作台 AI 能力的占位实现;
本模块是「AI 预约审查」专用的真实模型调用,读取模型管理里启用的 AIModelConfig,
发起 OpenAI 兼容的 chat/completions 请求(DeepSeek / Qwen / OpenAI / Azure 等均可)。
"""

from __future__ import annotations

import httpx

from app.models.ai_model import AIModelConfig


class LLMCallError(Exception):
    """模型调用失败(网络不可达 / 认证失败 / 响应异常),上层捕获后转「审查失败」结论。"""


def _http_error_detail(resp: httpx.Response) -> str:
    """从 4xx/5xx 响应里尽量抠出可读的错误信息(OpenAI/DashScope 多为 {error:{message}})。

    抠不到就退回原样文本,并截断到 300 字,避免把长文本/正文刷进「审查失败」留痕。
    """
    detail = ""
    try:
        body = resp.json()
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                detail = str(err.get("message") or "")
            else:
                detail = str(body.get("message") or "")
    except (ValueError, TypeError):
        detail = ""
    if not detail:
        detail = (resp.text or "").strip()
    if len(detail) > 300:
        detail = detail[:300] + "…"
    return detail or "（无响应体）"


async def chat_completion(
    messages: list[dict],
    config: AIModelConfig,
    *,
    timeout: float = 120.0,
) -> str:
    """调用启用模型的 chat/completions,返回模型输出文本。失败抛 LLMCallError。"""
    base_url = (config.base_url or "").rstrip("/")
    url = f"{base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {config.api_key or ''}"}
    payload: dict = {
        "model": config.model_name,
        "messages": messages,
        "temperature": config.temperature if config.temperature is not None else 0.2,
        "response_format": {"type": "json_object"},
    }
    if config.max_tokens is not None:
        payload["max_tokens"] = config.max_tokens

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            body = resp.json()
    except httpx.HTTPStatusError as exc:
        raise LLMCallError(
            f"模型接口返回 {exc.response.status_code}: {_http_error_detail(exc.response)}"
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise LLMCallError(f"模型调用失败: {exc}") from exc

    choices = body.get("choices") or []
    if not choices:
        raise LLMCallError("模型返回无 choices")
    content = (choices[0].get("message") or {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise LLMCallError("模型返回内容为空")
    return content
