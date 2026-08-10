import { apiClient } from "@/api/client";

export interface Party {
  party_type: "natural" | "company";
  name: string;
  id_number: string | null;
  gender: string | null;
  ethnicity: string | null;
  birth_date: string | null;
  address: string | null;
  phone: string | null;
  work_place: string | null;
  position: string | null;
  entry_date: string | null;
  monthly_wage: string | null;
  claims: string | null;
  requests: string[];
  facts: string | null;
  legal_person: string | null;
  legal_title: string | null;
}

export interface Evidence {
  name: string;
  content: string | null;
  pages: string | null;
}

export interface VirtualCase {
  id: string;
  receipt_number: string;
  /** pending=待录入内网 / recorded=已录入 */
  status: "pending" | "recorded";
  case_reason: string | null;
  claims: string | null;
  note: string | null;
  applicants: Party[];
  respondents: Party[];
  evidences: Evidence[];
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface VirtualCasePayload {
  case_reason: string | null;
  claims: string | null;
  note: string | null;
  applicants: Party[];
  respondents: Party[];
  evidences: Evidence[];
}

export function listVirtualCases() {
  return apiClient.get<VirtualCase[]>("/virtual-cases").then((res) => res.data);
}

export function createVirtualCase(payload: VirtualCasePayload) {
  return apiClient.post<VirtualCase>("/virtual-cases", payload).then((res) => res.data);
}

export function updateVirtualCase(id: string, payload: VirtualCasePayload) {
  return apiClient.put<VirtualCase>(`/virtual-cases/${id}`, payload).then((res) => res.data);
}

export function deleteVirtualCase(id: string) {
  return apiClient.delete(`/virtual-cases/${id}`);
}

export function updateVirtualCaseStatus(id: string, status: "pending" | "recorded") {
  return apiClient
    .put<VirtualCase>(`/virtual-cases/${id}/status`, { status })
    .then((res) => res.data);
}

export function downloadApplication(id: string) {
  return apiClient.get(`/virtual-cases/${id}/application`, { responseType: "blob" });
}

export function lookupPerson(idCard: string) {
  return apiClient
    .get<{ data?: Record<string, string> }>("/virtual-cases/lookup/person", {
      params: { id_card: idCard },
    })
    .then((res) => res.data);
}

export function lookupCompany(name: string) {
  return apiClient
    .get<{ data?: Record<string, string>[] }>("/virtual-cases/lookup/company", {
      params: { name },
    })
    .then((res) => res.data);
}
