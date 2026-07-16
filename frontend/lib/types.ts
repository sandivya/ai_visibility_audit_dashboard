export type UserRole = "owner" | "admin" | "member" | "viewer";
export type User = {
  id: string;
  email: string;
  org_id: string;
  organization_name: string;
  role: UserRole;
};
export type AuthConfig = {
  mock_auth_enabled: boolean;
  oidc_enabled: boolean;
  oidc_login_url: string | null;
};
export type CursorPage<T> = { items: T[]; next_cursor: string | null };
export type AuditStatus = "queued" | "processing" | "completed" | "failed";
export type RecommendationStatus = "open" | "in_progress" | "completed" | "dismissed";
export type EvidenceKind = "pages" | "prompts";
export type AuditMethodology = {
  mode: "simulated";
  version: string;
  disclosure: string;
  scoring_summary: string;
  stable_inputs: string[];
};
export type AuditSummary = {
  id: string;
  status: AuditStatus;
  visibility_score: number | null;
  created_at: string;
  updated_at: string;
  methodology: AuditMethodology;
};
export type Project = {
  id: string;
  name: string;
  domain: string;
  competitors: string[];
  created_at: string;
  updated_at: string;
  latest_audit: AuditSummary | null;
};
export type Finding = {
  id: string;
  audit_id: string;
  project_id: string;
  project_name: string;
  severity: string;
  category: string;
  evidence_kind: EvidenceKind;
  title: string;
  description: string;
  created_at: string;
};
export type Recommendation = {
  id: string;
  audit_id: string;
  priority: string;
  title: string;
  description: string;
  status: RecommendationStatus;
  evidence_kind: EvidenceKind;
  related_finding_id: string | null;
  related_finding_category: string | null;
  created_at: string;
  updated_at: string;
};
export type AuditPageEvidence = {
  id: string;
  url: string;
  title: string;
  status_code: number;
  created_at: string;
};
export type AuditPromptEvidence = {
  id: string;
  prompt: string;
  mentioned_brand: boolean;
  competitors_mentioned: string[];
  source: string;
  created_at: string;
};
export type AuditEvent = { id: string; event_type: string; message: string; created_at: string };
export type AuditStatusDetail = Pick<
  AuditSummary,
  "id" | "status" | "visibility_score" | "updated_at"
> & {
  project_id: string;
  error_message: string | null;
  retryable: boolean;
  failure_kind: "deterministic_demo" | null;
};
export type Audit = AuditSummary & {
  project_id: string;
  error_message: string | null;
  retryable: boolean;
  failure_kind: "deterministic_demo" | null;
  pages: AuditPageEvidence[];
  prompts: AuditPromptEvidence[];
  findings: Finding[];
  recommendations: Recommendation[];
  events: AuditEvent[];
  page_count: number;
  prompt_count: number;
  finding_count: number;
  recommendation_count: number;
  event_count: number;
  pages_next_cursor: string | null;
  prompts_next_cursor: string | null;
  findings_next_cursor: string | null;
  recommendations_next_cursor: string | null;
  events_next_cursor: string | null;
};
