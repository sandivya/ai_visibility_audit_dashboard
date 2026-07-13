import type {
  Audit,
  AuditPageEvidence,
  AuditPromptEvidence,
  AuditStatusDetail,
  Finding,
} from "@/lib/types";

type AuditVersion = Pick<Audit, "status" | "updated_at">;
type StatusVersion = Pick<AuditStatusDetail, "status" | "updated_at">;

export function isAuditFinalizing(
  audit: AuditVersion | undefined,
  status: StatusVersion | undefined,
  activity: { auditIsFetching: boolean; evidenceIsRefreshing: boolean },
) {
  if (status?.status !== "completed") return false;
  const baseHasTerminalVersion =
    audit?.status === "completed" && Date.parse(audit.updated_at) >= Date.parse(status.updated_at);
  return !baseHasTerminalVersion || activity.auditIsFetching || activity.evidenceIsRefreshing;
}

export function scoreNarrative(score: number | null) {
  if (score === null)
    return "The visibility score will appear after the audit evidence is finalized.";
  if (score >= 80)
    return "Strong visibility: the brand is consistently represented across the audited signals.";
  if (score >= 60)
    return "Developing visibility: the brand has a useful foundation with clear opportunities to improve coverage.";
  return "Visibility at risk: prioritize the high-impact gaps below to improve brand representation in AI answers.";
}

export function summarizeAuditEvidence(
  prompts: AuditPromptEvidence[],
  findings: Finding[],
  pages: AuditPageEvidence[],
) {
  const brandMentions = prompts.filter((prompt) => prompt.mentioned_brand).length;
  const mentionRate =
    prompts.length > 0 ? Math.round((brandMentions / prompts.length) * 100) : null;
  const uniqueCompetitors = new Set(
    prompts.flatMap((prompt) =>
      prompt.competitors_mentioned.map((competitor) => competitor.toLowerCase()),
    ),
  ).size;
  const severityCounts = findings.reduce(
    (counts, finding) => {
      const severity = finding.severity.toLowerCase();
      if (severity === "high" || severity === "medium" || severity === "low") counts[severity] += 1;
      return counts;
    },
    { high: 0, medium: 0, low: 0 },
  );
  const healthyPages = pages.filter(
    (page) => page.status_code >= 200 && page.status_code < 400,
  ).length;
  const pageHealthRate = pages.length > 0 ? Math.round((healthyPages / pages.length) * 100) : null;

  return { brandMentions, mentionRate, uniqueCompetitors, severityCounts, pageHealthRate };
}

export function safeEvidenceUrl(url: string) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.toString() : null;
  } catch {
    return null;
  }
}
