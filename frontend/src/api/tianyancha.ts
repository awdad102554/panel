import { apiClient } from "@/api/client";

/** 天眼查查企业结果(后端归一化:fields 为中文企业字段列表,raw 为原始对象)。 */
export interface TianyanchaCompanyResult {
  query: string;
  tool: string | null;
  fields: Record<string, unknown>[];
  raw: unknown;
}

export function lookupCompany(name: string) {
  return apiClient
    .get<{ data?: TianyanchaCompanyResult }>("/tianyancha/lookup/company", {
      params: { name },
    })
    .then((res) => res.data);
}

/** 企业详情(基础画像):概览字段 + 明细表。 */
export interface CompanyDetailField {
  "字段": string;
  "值": string;
}

export interface CompanyDetailTable {
  title: string;
  headers: string[];
  rows: Record<string, string>[];
}

export interface CompanyDetails {
  company_name: string;
  tool: string | null;
  overview: CompanyDetailField[];
  details: CompanyDetailTable[];
  raw: string | null;
}

export function lookupCompanyDetails(name: string) {
  return apiClient
    .get<{ data?: CompanyDetails }>("/tianyancha/lookup/details", {
      params: { name },
    })
    .then((res) => res.data);
}

export interface TianyanchaTool {
  name: string | null;
  description: string | null;
}

export function listTools() {
  return apiClient
    .get<{ data?: TianyanchaTool[] }>("/tianyancha/tools")
    .then((res) => res.data);
}

export interface TianyanchaConfig {
  configured: boolean;
  api_key_masked: string;
  /** db=页面保存 / env=.env 配置 / null=未配置 */
  source: "db" | "env" | null;
}

export function getTianyanchaConfig() {
  return apiClient
    .get<{ data?: TianyanchaConfig }>("/tianyancha/config")
    .then((res) => res.data);
}

export function updateTianyanchaConfig(apiKey: string) {
  return apiClient
    .put<{ data?: TianyanchaConfig }>("/tianyancha/config", { api_key: apiKey })
    .then((res) => res.data);
}
