import { apiClient } from "@/api/client";
import type { AIOutput } from "@/types";

export type AICapability =
  | "intake_review"
  | "case_understanding"
  | "legal_analysis"
  | "decision_draft";

export function invokeAICapability(caseId: string, capability: AICapability) {
  return apiClient
    .post<AIOutput>(`/cases/${caseId}/ai/invoke`, { capability })
    .then((res) => res.data);
}

export function confirmAIOutput(caseId: string, aiOutputId: string) {
  return apiClient
    .post<AIOutput>(`/cases/${caseId}/ai/${aiOutputId}/confirm`)
    .then((res) => res.data);
}
