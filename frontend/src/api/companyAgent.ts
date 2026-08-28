/** 企业委托代理人数据库 API */

import { apiClient } from "./client";

/** 代理人信息 */
export interface AgentInfo {
  agent_name: string;
  agent_type: number;
  agent_type_label: string;
  agent_phone: string | null;
  agent_law_firm: string | null;
  agent_id_number: string | null;
  case_no: string | null;
  filed_at: string | null;
  external_case_id: string;
  party_role: string;
  company_name: string;
  company_credit_code: string | null;
}

/** 案件信息 */
export interface CaseInfo {
  company_name: string;
  company_credit_code: string | null;
  agent_name: string;
  agent_type: number;
  agent_type_label: string;
  agent_phone: string | null;
  agent_law_firm: string | null;
  case_no: string | null;
  filed_at: string | null;
  external_case_id: string;
  party_role: string;
}

/** 按公司查询代理人响应 */
export interface CompanyAgentsResponse {
  company_name: string;
  total: number;
  agents: AgentInfo[];
}

/** 按代理人查询案件响应 */
export interface AgentCasesResponse {
  agent_name: string;
  total: number;
  cases: CaseInfo[];
}

/** 初始化响应 */
export interface InitializeResponse {
  success: boolean;
  inserted: number;
  updated: number;
  message: string;
}

/**
 * 查询某公司历年使用的所有代理人
 */
export function getAgentsByCompany(companyName: string) {
  return apiClient
    .get<CompanyAgentsResponse>("/company-agents/by-company", {
      params: { company_name: companyName },
    })
    .then((res) => res.data);
}

/**
 * 查询某代理人历年代理过的所有案件
 */
export function getCasesByAgent(agentName: string) {
  return apiClient
    .get<AgentCasesResponse>("/company-agents/by-agent", {
      params: { agent_name: agentName },
    })
    .then((res) => res.data);
}

/**
 * 从所有快照初始化企业代理人数据库（一次性操作）
 */
export function initializeCompanyAgentDatabase() {
  return apiClient
    .post<InitializeResponse>("/company-agents/initialize")
    .then((res) => res.data);
}

/**
 * 公司名称自动补全
 */
export function autocompleteCompanies(query: string) {
  return apiClient
    .get<string[]>("/company-agents/autocomplete/companies", {
      params: { q: query, limit: 10 },
    })
    .then((res) => res.data);
}

/**
 * 代理人姓名自动补全
 */
export function autocompleteAgents(query: string) {
  return apiClient
    .get<string[]>("/company-agents/autocomplete/agents", {
      params: { q: query, limit: 10 },
    })
    .then((res) => res.data);
}
