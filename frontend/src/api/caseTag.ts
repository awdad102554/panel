import { apiClient } from "@/api/client";

/** 案件记事本(时间/设备IP/环节/操作人服务端自动落,内容用户填)。 */
export interface CaseTag {
  id: string;
  subject_key: string;
  content: string;
  stage: string;
  operator: string;
  client_ip: string;
  created_at: string;
}

export function listCaseTags(subjectKey: string) {
  return apiClient
    .get<CaseTag[]>(`/case-tags/${encodeURIComponent(subjectKey)}`)
    .then((res) => res.data);
}

export function createCaseTag(subjectKey: string, content: string) {
  return apiClient
    .post<CaseTag>(`/case-tags/${encodeURIComponent(subjectKey)}`, { content })
    .then((res) => res.data);
}

/** 记事本快捷内容(所有用户共享,与 InfoWeb 同一张表)。 */
export interface CaseTagPhrase {
  id: number;
  content: string;
  operator: string;
  created_at: string;
}

export function listCaseTagPhrases() {
  return apiClient.get<CaseTagPhrase[]>("/case-tag-phrases").then((res) => res.data);
}

export function createCaseTagPhrase(content: string) {
  return apiClient.post<CaseTagPhrase>("/case-tag-phrases", { content }).then((res) => res.data);
}

export function deleteCaseTagPhrase(id: number) {
  return apiClient.delete(`/case-tag-phrases/${id}`).then((res) => res.data);
}

/** 记事本总览条目:近 N 天有记事的案件(案号/当事人取案件当前口径)。 */
export interface CaseNoteOverviewItem {
  subject_key: string;
  /** 当前案号(收件转立案后为立案案号;预登记为收件编号);null = 案件已删除/未同步 */
  case_no: string | null;
  applicant: string | null;
  respondent: string | null;
  /** 当前环节码(reserve/receive/pre_mediation/handle/.../virtual) */
  stage: string;
  tag_count: number;
  last_content: string;
  last_operator: string;
  last_at: string;
  exists: boolean;
}

export interface CaseNoteOverview {
  days: number;
  total: number;
  items: CaseNoteOverviewItem[];
}

/** 记事本总览:days 不传时后端用"时限设置"的记事本总览天数(默认 30)。 */
export function getCaseNotesOverview(days?: number) {
  return apiClient
    .get<CaseNoteOverview>("/case-tags/overview", { params: days ? { days } : {} })
    .then((res) => res.data);
}
