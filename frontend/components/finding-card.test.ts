import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Finding } from "@/lib/types";
import { FindingCard } from "./finding-card";

describe("FindingCard", () => {
  it("links project and audit context", () => {
    const finding: Finding = {
      id: "finding_1",
      audit_id: "audit_12345678",
      project_id: "project_1",
      project_name: "Acme",
      severity: "high",
      category: "ai_visibility",
      evidence_kind: "prompts",
      title: "Brand is absent",
      description: "The brand did not appear in audited prompts.",
      created_at: "2026-07-13T00:00:00Z",
    };

    const markup = renderToStaticMarkup(
      createElement(FindingCard, { item: finding, showContext: true }),
    );

    expect(markup).toContain('href="/projects/project_1"');
    expect(markup).toContain('href="/audits/audit_12345678"');
    expect(markup).toContain('id="finding-finding_1"');
    expect(markup).toContain('aria-labelledby="finding-finding_1-title"');
    expect(markup).toContain('id="finding-finding_1-title"');
    expect(markup).toContain("Acme");
  });
});
