import { apiClient } from "@/api/client";
import type { InternalCase, InternalCaseUrgency, InternalStage } from "@/types";

export function listInternalCases(filters?: {
  stage?: InternalStage;
  urgency?: InternalCaseUrgency;
  includeClosed?: boolean;
}) {
  return apiClient
    .get<InternalCase[]>("/internal-cases", {
      params: {
        stage: filters?.stage,
        urgency: filters?.urgency,
        include_closed: filters?.includeClosed ?? false,
      },
    })
    .then((res) => res.data);
}

export function upsertOverride(externalCaseId: string, deadlineOverride: string, note?: string) {
  return apiClient
    .put<InternalCase>(`/internal-cases/${externalCaseId}/override`, {
      deadline_override: deadlineOverride,
      note: note || null,
    })
    .then((res) => res.data);
}

export function deleteOverride(externalCaseId: string) {
  return apiClient.delete(`/internal-cases/${externalCaseId}/override`);
}

export function triggerSync(full = false) {
  return apiClient
    .post<{ counts: Record<string, number> }>("/internal-cases/sync", null, {
      params: { full },
    })
    .then((res) => res.data);
}

export interface ConsistencyReport {
  checked: number;
  missing_total: number;
  mismatch_total: number;
  only_in_snapshot: number;
  missing_in_snapshot: { case_no: string | null; stage: string; current_step: string | null }[];
  field_mismatches: { case_no: string | null; field: string; snapshot: unknown; intranet: unknown }[];
}

export function verifyConsistency() {
  return apiClient
    .post<ConsistencyReport>("/internal-cases/verify-consistency", null, { timeout: 600000 })
    .then((res) => res.data);
}
