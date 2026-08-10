import { apiClient } from "@/api/client";

export interface TimeLimitItem {
  key: string;
  label: string;
  value: number;
  default: number;
  description: string;
  minimum: number;
  maximum: number;
}

export function getTimeLimits() {
  return apiClient.get<{ items: TimeLimitItem[] }>("/settings/time-limits").then((res) => res.data.items);
}

export function updateTimeLimits(values: Record<string, number>) {
  return apiClient
    .put<{ items: TimeLimitItem[] }>("/settings/time-limits", { values })
    .then((res) => res.data.items);
}

export function resetTimeLimits() {
  return apiClient
    .post<{ items: TimeLimitItem[] }>("/settings/time-limits/reset")
    .then((res) => res.data.items);
}
