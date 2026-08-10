from typing import Any

from app.ai.base import AICapability, AIResult
from app.ai.client import get_llm_client


class LegalAnalysisCapability(AICapability):
    """法律分析 AI，对应 03 文档阶段八 / 05 文档第十章。

    输出《法律分析》：争议焦点、查明事实、证据采信建议、法律依据、分析意见。
    AI 不直接决定是否采信证据，由仲裁员确认。
    """

    name = "legal_analysis"

    async def run(self, case_context: dict[str, Any]) -> AIResult:
        client = get_llm_client()
        raw = await client.complete(self._build_prompt(case_context))
        return AIResult(
            summary=raw.get("summary", ""),
            issues=raw.get("issues", []),
            risks=raw.get("risks", []),
            suggestions=raw.get("suggestions", []),
            references=raw.get("references", []),
            extra={"legal_basis": raw.get("legal_basis", [])},
        )

    @staticmethod
    def _build_prompt(case_context: dict[str, Any]) -> str:
        return (
            "请基于案件理解结果进行法律分析，输出争议焦点、证据采信建议及法律依据：\n"
            f"{case_context}"
        )
