from typing import Any

from app.ai.base import AICapability, AIResult
from app.ai.client import get_llm_client


class DecisionDraftCapability(AICapability):
    """裁决书生成 AI，对应 03 文档阶段九 / 05 文档第十二、十三章。

    输入案件理解 + 法律分析 + 仲裁员确认结果，输出裁决书初稿，
    随后执行一致性检查（金额/日期/主体/法律引用/格式），最终由仲裁员修改确认。
    """

    name = "decision_draft"

    async def run(self, case_context: dict[str, Any]) -> AIResult:
        client = get_llm_client()
        raw = await client.complete(self._build_prompt(case_context))
        return AIResult(
            summary=raw.get("summary", ""),
            issues=raw.get("issues", []),
            risks=raw.get("risks", []),
            suggestions=raw.get("suggestions", []),
            references=raw.get("references", []),
            extra={"draft_content": raw.get("draft_content", "")},
        )

    @staticmethod
    def _build_prompt(case_context: dict[str, Any]) -> str:
        return (
            "请基于案件理解与法律分析结果生成裁决书初稿（首部/查明事实/本委认为/裁决结果/尾部）：\n"
            f"{case_context}"
        )
