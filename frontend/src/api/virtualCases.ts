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

// ---- 提交到内网 ----

export interface CatalogNode {
  id: number;
  code: string;
  name: string;
}

export interface CatalogItem {
  path: CatalogNode[];
  options: string[];
  template: string;
}

export interface SubmitDraftRequest {
  text: string;
  path_ids: number[] | null;
  path_names: string[] | null;
  option: string | null;
  object: number | null;
  intro: string | null;
  guessed: boolean;
}

export interface SubmitDraft {
  defaults: {
    apply_at: string;
    town_id: number;
    case_reason: string;
    is_sign_labor_contract: number;
    is_pay_social_insurance: number;
    company_nature: string;
    position: { Id: number; name: string }[];
  };
  requests: SubmitDraftRequest[];
  respondents: Party[];
  company_fills: { name: string; found: boolean; registered_capital?: string | number }[];
  errors: string[];
  warnings: string[];
  meta: {
    towns: { town_id: number; town_name: string }[];
    case_reasons: string[];
    company_natures: string[];
    catalog: CatalogItem[];
  };
}

export interface RequestSpec {
  text: string;
  path_ids: number[];
  option: string | null;
  object: number | null;
  intro: string | null;
}

export interface SubmitSpec {
  apply_at: string;
  town_id: number;
  case_reason: string;
  is_sign_labor_contract: number;
  is_pay_social_insurance: number;
  company_nature: string;
  requests: RequestSpec[];
}

export function fetchSubmitDraft(id: string) {
  return apiClient.post<SubmitDraft>(`/virtual-cases/${id}/submit-draft`).then((res) => res.data);
}

export function submitPreview(id: string, spec: SubmitSpec) {
  return apiClient
    .post<Record<string, unknown>>(`/virtual-cases/${id}/submit-preview`, spec)
    .then((res) => res.data);
}

export function submitToInternal(id: string, spec: SubmitSpec) {
  return apiClient
    .post<{ code: number; data: unknown }>(`/virtual-cases/${id}/submit`, spec)
    .then((res) => res.data);
}
