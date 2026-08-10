import { apiClient } from "@/api/client";
import type { Case, CaseStatus, TimelineEvent } from "@/types";

export function createCase(claims?: string) {
  return apiClient.post<Case>("/cases", { claims }).then((res) => res.data);
}

export function getCase(caseId: string) {
  return apiClient.get<Case>(`/cases/${caseId}`).then((res) => res.data);
}

export function transitionCase(caseId: string, targetStatus: CaseStatus) {
  return apiClient
    .post<Case>(`/cases/${caseId}/transition`, { target_status: targetStatus })
    .then((res) => res.data);
}

export function getCaseTimeline(caseId: string) {
  return apiClient.get<TimelineEvent[]>(`/cases/${caseId}/timeline`).then((res) => res.data);
}

export function getCasePortrait(caseId: string) {
  return apiClient.get(`/cases/${caseId}/portrait`).then((res) => res.data);
}
