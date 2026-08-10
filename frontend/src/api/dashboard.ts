import { apiClient } from "@/api/client";
import type { DashboardCharts, DashboardSummary, HearingList, InternalCase } from "@/types";

export function getDashboardSummary() {
  return apiClient.get<DashboardSummary>("/dashboard/summary").then((res) => res.data);
}

export function getUpcomingHearings() {
  return apiClient.get<HearingList>("/dashboard/hearings").then((res) => res.data);
}

export function getCardCases(key: string) {
  return apiClient
    .get<InternalCase[]>("/dashboard/card-cases", { params: { key } })
    .then((res) => res.data);
}

export function getDashboardCharts() {
  return apiClient.get<DashboardCharts>("/dashboard/charts").then((res) => res.data);
}

export function getChartCases(kind: string, value: string) {
  return apiClient
    .get<InternalCase[]>("/dashboard/chart-cases", { params: { kind, value } })
    .then((res) => res.data);
}
