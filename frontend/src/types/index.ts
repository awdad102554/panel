export type CaseStatus =
  | "received"
  | "pre_review"
  | "mediation"
  | "filed"
  | "pre_hearing"
  | "hearing"
  | "post_hearing"
  | "decision"
  | "service"
  | "archived";

export type PartyType = "applicant" | "respondent";

export interface Party {
  id: string;
  party_type: PartyType;
  name: string;
  id_card_or_credit_code: string | null;
}

export interface Case {
  id: string;
  case_no: string | null;
  status: CaseStatus;
  claims: string | null;
  risk_level: string | null;
  filed_date: string | null;
  statute_deadline: string | null;
  created_at: string;
  updated_at: string;
  parties: Party[];
}

export type InternalStage = "reserve" | "receive" | "handle" | "virtual";

export type InternalCaseUrgency =
  | "overdue"
  | "urgent"
  | "soon"
  | "normal"
  | "paused"
  | "paused_overdue"
  | "closed"
  | "rejected";

export interface InternalCase {
  external_case_id: string;
  stage: InternalStage;
  current_step: string | null;
  case_no: string | null;
  applicant: string | null;
  respondent: string | null;
  is_paused: boolean;
  native_remaining_days: number | null;
  extension_days: number;
  end_at: string | null;
  end_way: string | null;
  phase_entered_at: string;
  last_synced_at: string;
  /** 服务端读取时实时计算的紧急度 */
  urgency: InternalCaseUrgency;
  days_remaining: number | null;
  urgency_source: "override" | "native" | "elapsed" | "status";
  has_override: boolean;
  override_deadline: string | null;
}

export interface TimelineEvent {
  id: string;
  case_id: string;
  event_type: string;
  summary: string;
  created_by: string | null;
  created_at: string;
}

export interface AIResult {
  summary: string;
  issues: string[];
  risks: string[];
  suggestions: string[];
  references: string[];
  extra: Record<string, unknown>;
}

export interface AIOutput {
  id: string;
  case_id: string;
  capability: string;
  result: AIResult;
  created_at: string;
  confirmed_at: string | null;
  confirmed_by: string | null;
}

export interface DashboardSummary {
  due_reminders: number;
  hearings_upcoming: number;
  pending_mediation: number;
  pending_receive: number;
  open_cases: number;
  heard_awaiting_decision: number;
  paused_long: number;
  today_filed: number;
  today_closed: number;
  /** 数据来源:internal = 内网案件系统真实数据,local = 本地模拟/空数据回退 */
  source: "internal" | "local";
}

export interface MonthlyTrendPoint {
  month: string;
  filed: number;
  closed: number;
}

export interface NameCount {
  name: string;
  count: number;
}

export interface DashboardCharts {
  monthly_trend: MonthlyTrendPoint[];
  open_steps: NameCount[];
  end_ways: NameCount[];
  urgency: NameCount[];
}

export interface StatsKpis {
  receive_total: number;
  filed_total: number;
  open_cases: number;
  closed_cases: number;
  mediation_rate: number;
  avg_duration_days: number;
  overdue_cases: number;
  over_limit_open: number;
  over_limit_closed: number;
}

export interface PersonStat {
  name: string;
  total: number;
  open: number;
  closed: number;
}

export interface YearStats {
  year: number;
  filed: number;
  closed: number;
  mediation_rate: number;
  avg_duration_days: number;
}

export interface YearCompare {
  this_year: YearStats;
  last_year: YearStats;
  monthly_filed_this: number[];
  monthly_filed_last: number[];
  monthly_closed_this: number[];
  monthly_closed_last: number[];
}

export interface YearlyStats {
  year: number;
  filed: number;
  closed: number;
  mediation_rate: number;
  avg_duration_days: number;
  monthly_filed: number[];
  monthly_closed: number[];
  available_years: number[];
}

export interface StatsOverview {
  /** 数据来源:internal = 内网案件系统真实数据,local = 本地模拟/空数据回退 */
  source: "internal" | "local";
  kpis: StatsKpis;
  monthly_trend: MonthlyTrendPoint[];
  end_ways: NameCount[];
  duration_buckets: NameCount[];
  arbitrator_stats: PersonStat[];
  year_compare: YearCompare | null;
}

export interface Hearing {
  case_no: string;
  case_id: string | null;
  open_at: string;
  end_at: string | null;
  tribunal_name: string | null;
  arbitrator: string | null;
  clerk: string | null;
  current_step: string | null;
  applicant: string | null;
  respondent: string | null;
}

export interface HearingList {
  start: string;
  end: string;
  total: number;
  items: Hearing[];
}

export interface AIModelConfig {
  id: string;
  name: string;
  provider: string;
  base_url: string;
  api_key_masked: string;
  model_name: string;
  temperature: number | null;
  max_tokens: number | null;
  is_enabled: boolean;
  remark: string | null;
  created_at: string;
  updated_at: string;
}
