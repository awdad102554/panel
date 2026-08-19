import { apiClient } from "@/api/client";
import type { AIModelConfig } from "@/types";

export interface AIModelPayload {
  name: string;
  provider: string;
  base_url: string;
  api_key?: string;
  model_name: string;
  temperature?: number | null;
  max_tokens?: number | null;
  supports_vision?: boolean;
  remark?: string | null;
}

export function listModels() {
  return apiClient.get<AIModelConfig[]>("/ai-models").then((res) => res.data);
}

export function getActiveModel() {
  return apiClient.get<AIModelConfig | null>("/ai-models/active").then((res) => res.data);
}

export function createModel(payload: AIModelPayload) {
  return apiClient.post<AIModelConfig>("/ai-models", payload).then((res) => res.data);
}

export function updateModel(id: string, payload: Partial<AIModelPayload>) {
  return apiClient.put<AIModelConfig>(`/ai-models/${id}`, payload).then((res) => res.data);
}

export function deleteModel(id: string) {
  return apiClient.delete(`/ai-models/${id}`).then((res) => res.data);
}

export function enableModel(id: string) {
  return apiClient.post<AIModelConfig>(`/ai-models/${id}/enable`).then((res) => res.data);
}
