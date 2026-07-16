import { describe, expect, it } from "vitest";
import type { AuditPageEvidence, AuditPromptEvidence, Finding } from "@/lib/types";
import {
  auditEvidenceAnchor,
  isAuditFinalizing,
  safeEvidenceUrl,
  scoreNarrative,
  summarizeAuditEvidence,
} from "./view-model";

describe("audit view model", () => {
  it("routes findings to category-appropriate evidence", () => {
    expect(auditEvidenceAnchor("pages")).toBe("#page-evidence");
    expect(auditEvidenceAnchor("prompts")).toBe("#prompt-evidence");
  });

  it("keeps a terminal transition in finalizing state until audit and evidence refresh", () => {
    const status = { status: "completed" as const, updated_at: "2026-07-13T00:01:00Z" };

    expect(
      isAuditFinalizing({ status: "processing", updated_at: "2026-07-13T00:00:00Z" }, status, {
        auditIsFetching: true,
        evidenceIsRefreshing: true,
      }),
    ).toBe(true);
    expect(
      isAuditFinalizing({ status: "completed", updated_at: "2026-07-13T00:01:00Z" }, status, {
        auditIsFetching: false,
        evidenceIsRefreshing: false,
      }),
    ).toBe(false);
  });

  it("does not finalize active or failed statuses", () => {
    expect(
      isAuditFinalizing(
        undefined,
        { status: "processing", updated_at: "2026-07-13T00:00:00Z" },
        { auditIsFetching: false, evidenceIsRefreshing: false },
      ),
    ).toBe(false);
    expect(
      isAuditFinalizing(
        undefined,
        { status: "failed", updated_at: "2026-07-13T00:00:00Z" },
        { auditIsFetching: false, evidenceIsRefreshing: false },
      ),
    ).toBe(false);
  });

  it("summarizes mention, competitor, severity, and page-health evidence", () => {
    const prompts: AuditPromptEvidence[] = [
      {
        id: "p1",
        prompt: "one",
        mentioned_brand: true,
        competitors_mentioned: ["Rival.com"],
        source: "model",
        created_at: "2026-07-13T00:00:00Z",
      },
      {
        id: "p2",
        prompt: "two",
        mentioned_brand: false,
        competitors_mentioned: ["rival.com", "Other.com"],
        source: "model",
        created_at: "2026-07-13T00:00:00Z",
      },
    ];
    const findings = ["high", "medium", "low", "informational"].map((severity, index): Finding => ({
      id: `f${index}`,
      audit_id: "a1",
      project_id: "project_1",
      project_name: "Example",
      severity,
      category: "ai_visibility",
      evidence_kind: "prompts",
      title: severity,
      description: severity,
      created_at: "2026-07-13T00:00:00Z",
    }));
    const pages: AuditPageEvidence[] = [
      {
        id: "one",
        url: "https://example.com",
        title: "One",
        status_code: 200,
        created_at: "2026-07-13T00:00:00Z",
      },
      {
        id: "two",
        url: "https://example.com/missing",
        title: "Two",
        status_code: 404,
        created_at: "2026-07-13T00:00:00Z",
      },
    ];

    expect(summarizeAuditEvidence(prompts, findings, pages)).toEqual({
      brandMentions: 1,
      mentionRate: 50,
      uniqueCompetitors: 2,
      severityCounts: { high: 1, medium: 1, low: 1 },
      pageHealthRate: 50,
    });
    expect(summarizeAuditEvidence([], [], [])).toMatchObject({
      mentionRate: null,
      pageHealthRate: null,
    });
  });

  it("describes every score band", () => {
    expect(scoreNarrative(null)).toContain("will appear");
    expect(scoreNarrative(85)).toContain("Strong visibility");
    expect(scoreNarrative(65)).toContain("Developing visibility");
    expect(scoreNarrative(40)).toContain("at risk");
  });

  it("allows only valid HTTP evidence links", () => {
    expect(safeEvidenceUrl("https://example.com/path")).toBe("https://example.com/path");
    expect(safeEvidenceUrl("javascript:alert(1)")).toBeNull();
    expect(safeEvidenceUrl("not a url")).toBeNull();
  });
});
