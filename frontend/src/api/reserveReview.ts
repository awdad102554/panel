import { apiClient } from "@/api/client";
import type {
  PendingReserve,
  ReserveCaseDetail,
  ReserveReviewDecision,
  ReserveReviewResult,
  ReviewDecision,
  ReviewStepEvent,
} from "@/types";

export function listPendingReserve() {
  return apiClient.get<PendingReserve[]>("/reserve-reviews/pending").then((res) => res.data);
}

export function getLatestReview(externalCaseId: string) {
  return apiClient
    .get<ReserveReviewResult>(`/reserve-reviews/${externalCaseId}`)
    .then((res) => res.data);
}

export function getReviewDecision(externalCaseId: string) {
  return apiClient
    .get<ReserveReviewDecision>(`/reserve-reviews/${externalCaseId}/decision`)
    .then((res) => res.data);
}

export function submitReviewDecision(
  externalCaseId: string,
  body: { decision: ReviewDecision; reject_reason: string | null; reject_detail: string | null },
) {
  return apiClient
    .post<ReserveReviewDecision>(`/reserve-reviews/${externalCaseId}/decision`, body)
    .then((res) => res.data);
}

export function getReserveDetail(externalCaseId: string) {
  return apiClient
    .get<ReserveCaseDetail>(`/reserve-reviews/${externalCaseId}/detail`)
    .then((res) => res.data);
}

/** 流式审查一件待审核预约:用 fetch 消费后端 NDJSON 逐步事件,回调每个事件,返回最终结论。 */
export async function reviewReserve(
  externalCaseId: string,
  onEvent: (ev: ReviewStepEvent) => void,
): Promise<ReserveReviewResult> {
  const resp = await fetch(`/api/v1/reserve-reviews/${externalCaseId}/review`, { method: "POST" });
  if (!resp.ok || !resp.body) {
    throw new Error(`审查请求失败（${resp.status}）`);
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: ReserveReviewResult | null = null;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      const text = line.trim();
      if (!text) continue;
      let ev: ReviewStepEvent;
      try {
        ev = JSON.parse(text) as ReviewStepEvent;
      } catch {
        continue;
      }
      onEvent(ev);
      if (ev.type === "result" && ev.data) result = ev.data;
    }
  }
  if (!result) throw new Error("未收到审查结果");
  return result;
}
