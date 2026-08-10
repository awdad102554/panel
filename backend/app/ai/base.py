from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class AIResult(BaseModel):
    """统一 AI 输出结构，对应 07 技术沟通说明"十一、AI 输出格式"。

    所有 AI 能力必须返回这个信封结构；不同能力可以在各自的 Capability 类里
    往 result 内部塞入更多字段（如争议焦点列表），但顶层字段保持一致，
    便于前端 AIAssistantPanel 统一渲染、统一走"人工确认"流程。
    """

    summary: str = Field(description="AI 总结")
    issues: list[str] = Field(default_factory=list, description="发现的问题/待查明事项")
    risks: list[str] = Field(default_factory=list, description="风险提示")
    suggestions: list[str] = Field(default_factory=list, description="建议")
    references: list[str] = Field(default_factory=list, description="引用材料/证据/法律依据定位")
    extra: dict[str, Any] = Field(default_factory=dict, description="能力特有的扩展字段")


class AICapability(ABC):
    """AI 能力抽象基类。

    业务层只依赖 `run()` 的输入输出契约，不关心具体 Prompt 或模型；
    真实 LLM 接入时只需替换 `app/ai/client.py` 里的 Provider 实现，
    各 Capability 子类无需改动（对应 07 文档"保持业务与 AI 解耦"）。
    """

    name: str

    @abstractmethod
    async def run(self, case_context: dict[str, Any]) -> AIResult:
        ...
