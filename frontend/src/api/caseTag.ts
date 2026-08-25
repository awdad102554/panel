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
