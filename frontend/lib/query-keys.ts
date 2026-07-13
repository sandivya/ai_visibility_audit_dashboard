export type AuditEvidenceKind = "pages" | "prompts" | "findings" | "recommendations" | "events";

export type FindingFilters = {
  severity?: string;
  category?: string;
  audit_id?: string;
  project_id?: string;
};

/**
 * Shared cache keys keep invalidation predictable without hiding request logic
 * behind pass-through hooks. The tuple shapes intentionally match the keys
 * used by the existing application so this can be adopted incrementally.
 */
export const queryKeys = {
  session: ["session"] as const,
  authConfig: ["auth-config"] as const,
  loginUsers: ["login-users"] as const,
  projects: ["projects"] as const,
  projectOptions: (search: string) => ["project-options", search] as const,
  auditOptions: (projectId: string) => ["audit-options", projectId] as const,
  project: (projectId: string) => ["project", projectId] as const,
  projectAudits: (projectId: string) => ["audits", projectId] as const,
  audit: (auditId: string) => ["audit", auditId] as const,
  auditStatus: (auditId: string) => ["audit-status", auditId] as const,
  auditEvidence: (auditId: string) => ["audit-evidence", auditId] as const,
  auditEvidenceKind: <Kind extends AuditEvidenceKind>(auditId: string, kind: Kind) =>
    ["audit-evidence", auditId, kind] as const,
  findings: (filters: FindingFilters) =>
    [
      "findings",
      filters.severity ?? "",
      filters.category ?? "",
      filters.project_id ?? "",
      filters.audit_id ?? "",
    ] as const,
  startAudit: (projectId: string) => ["start-audit", projectId] as const,
  updateRecommendation: (auditId: string) => ["update-recommendation", auditId] as const,
};
