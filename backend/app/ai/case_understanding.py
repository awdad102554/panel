from typing import Any

from app.ai.base import AICapability, AIResult
from app.ai.client import get_llm_client


class CaseUnderstandingCapability(AICapability):
    """案件理解 AI，对应 03 文档阶段七 / 05 文档第九章。

    输出《案件理解》：案件概况、双方主张、无争议事实、有争议事实、已知证据、待查明事项，
    作为后续法律分析的输入，仲裁员审核确认后才进入正式业务数据。
    """

    name = "case_understanding"

    async def run(self, case_context: dict[str, Any]) -> AIResult:
        client = get_llm_client()
        raw = await client.complete(self._build_prompt(case_context))
        return AIResult(
            summary=raw.get("summary", ""),
            issues=raw.get("issues", []),
            risks=raw.get("risks", []),
            suggestions=raw.get("suggestions", []),
            references=raw.get("references", []),
            extra={
                "disputed_facts": raw.get("disputed_facts", []),
                "undisputed_facts": raw.get("undisputed_facts", []),
            },
        )

    @staticmethod
    def _build_prompt(case_context: dict[str, Any]) -> str:
        return (
            "请基于以下案件资料（申请书、答辩意见、庭审记录、证据目录）整理《案件理解》：\n"
            f"{case_context}"
        )
