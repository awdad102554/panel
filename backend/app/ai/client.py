"""LLM Provider 占位封装。

当前返回 mock 数据，便于在没有真实模型接入的情况下跑通整条链路
（案件工作台 -> AI 能力中心 -> 结构化输出 -> 人工确认 -> 时间线）。

后续接入真实大语言模型时，只需实现 `complete()` 并在这里切换 Provider，
`app/ai/*.py` 下各 Capability 的调用方式不需要改动。
"""

from typing import Any


class LLMClient:
    async def complete(self, prompt: str, *, response_schema: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError


class MockLLMClient(LLMClient):
    """开发/演示阶段使用的占位实现，返回固定结构，不调用任何外部服务。"""

    async def complete(self, prompt: str, *, response_schema: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "summary": "（Mock）AI 服务尚未接入真实模型，这是占位输出。",
            "issues": [],
            "risks": [],
            "suggestions": [],
            "references": [],
        }


def get_llm_client() -> LLMClient:
    """返回当前 LLM 客户端。

    当前阶段无论"模型管理"里是否配置了启用项，都回退到 MockLLMClient——真实
    的 OpenAI 兼容 HTTP Provider 留待后续在此实现 `complete()`（读取启用配置的
    base_url/api_key/model_name 发起请求），届时各 Capability 无需改动。
    """

    return MockLLMClient()
