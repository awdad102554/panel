import { apiClient } from "@/api/client";
import type { StatsOverview, YearlyStats } from "@/types";

export function getStatsOverview() {
  return apiClient.get<StatsOverview>("/stats/overview").then((res) => res.data);
}

export function getYearlyStats(year: number) {
  return apiClient
    .get<YearlyStats>("/stats/yearly", { params: { year } })
    .then((res) => res.data);
}
