import { apiClient } from "@/api/client";

export interface Agent {
  name: string;
  /** 1法定 2指定 3近亲属 4团体/单位推荐 5单位工作人员 6律师 7法律服务工作者 */
  agent_type: number;
  id_type: string | null;
  id_number: string | null;
  mobile: string | null;
  sex: string | null;
  relation: string | null;
  select_other_content: string | null;
  agent_auth: string | null;
  law_firm_name: string | null;
  /** 1执业律师 2实习律师 */
  lawer_type: number | null;
  is_legal_aid: number | null;
  lawyer_card_number: string | null;
  address: string | null;
  receive_address: string | null;
  job: string | null;
}

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
  agents: Agent[];
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

/** 内网代理人登记记录(cases/Agent 原始字段)。 */
export interface AgentRecord {
  name: string;
  id_type?: string;
  id_number?: string;
  mobile?: string;
  sex?: string;
  agent_auth?: string;
  relation?: string;
  select_other_content?: string;
  law_firm_name?: string;
  lawer_type?: number;
  is_legal_aid?: number;
  lawyer_card_number?: string;
  address?: string;
  registered_permanent_residence?: string;
  receive_address?: string;
  job?: string;
  type?: (number | null)[];
}

export function lookupAgent(params: { name?: string; id_number?: string; mobile?: string }) {
  return apiClient
    .get<{ data?: AgentRecord[] }>("/virtual-cases/lookup/agent", { params })
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
    is_easy: number;
    company_nature: string;
    id_type: string;
    is_migrant_worker: number;
    is_three_woman_worker: number;
    position: { Id: number; name: string }[];
  };
  requests: SubmitDraftRequest[];
  respondents: Party[];
  company_fills: { name: string; found: boolean; registered_capital?: string | number }[];
  fact_content: string;
  fact_parts: {
    entry_date: string | null;
    work_place: string | null;
    position: string | null;
    monthly_wage: string | null;
  };
  errors: string[];
  warnings: string[];
  meta: {
    towns: { town_id: number; town_name: string }[];
    case_reasons: string[];
    company_natures: string[];
    worker_id_types: string[];
    catalog: CatalogItem[];
    main_cause_presets: string[];
    agent_types: { code: number; label: string }[];
    agent_relations: string[];
    agent_auths: string[];
    lawyer_types: { code: number; label: string }[];
  };
}

export interface RequestItem {
  name: string;
  object: number | null;
}

export interface RequestSpec {
  text: string;
  path_ids: number[];
  option: string | null;
  object: number | null;
  items: RequestItem[];
  start_at: string | null;
  end_at: string | null;
  intro: string | null;
}

export interface SubmitSpec {
  apply_at: string;
  town_id: number;
  case_reason: string;
  is_sign_labor_contract: number;
  is_pay_social_insurance: number;
  is_easy: number;
  company_nature: string;
  id_type: string;
  is_migrant_worker: number;
  is_three_woman_worker: number;
  main_causes: string[];
  fact_content: string | null;
  requests: RequestSpec[];
  /** 内网提示疑似重复案件后,用户确认仍要提交时置 true(后端用原 payload 重试一次) */
  force: boolean;
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
