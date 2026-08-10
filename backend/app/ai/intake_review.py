from typing import Any

from app.ai.base import AICapability, AIResult
from app.ai.client import get_llm_client


class IntakeReviewCapability(AICapability):
    """收件预审 AI，对应 03 文档阶段一 / 05 文档第五章。

    职责：主体校验、请求规范检查、材料完整性检查，输出必须补正/建议补正/风险提示，
    并全部定位到原文（AIResult.references）。AI 不认定事实、不替仲裁员做决定。
    """

    name = "intake_review"

    async def run(self, case_context: dict[str, Any]) -> AIResult:
        client = get_llm_client()
        prompt = self._build_prompt(case_context)
        raw = await client.complete(prompt)

        issues: list[str] = list(raw.get("issues", []))
        parties = case_context.get("parties", [])
        if not any(p.get("party_type") == "applicant" for p in parties):
            issues.append("缺少申请人信息")
        if not any(p.get("party_type") == "respondent" for p in parties):
            issues.append("缺少被申请人信息")
        if not case_context.get("claims"):
            issues.append("仲裁请求未填写，请补正")

        return AIResult(
            summary=raw.get("summary", ""),
            issues=issues,
            risks=raw.get("risks", []),
            suggestions=raw.get("suggestions", []),
            references=raw.get("references", []),
        )

    @staticmethod
    def _build_prompt(case_context: dict[str, Any]) -> str:
        return (
            "请对以下劳动人事争议仲裁收件材料进行规范性审查，"
            "输出主体校验结果、请求规范性、材料完整性及补正建议：\n"
            f"{case_context}"
        )
