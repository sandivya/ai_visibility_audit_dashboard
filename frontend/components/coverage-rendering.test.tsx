// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { usePageTitle } from "@/lib/use-page-title";
import { validateProjectDraft } from "@/lib/validation";
import { CopyIcon, ExternalLinkIcon, FindingsIcon, ProjectsIcon, RefreshIcon } from "./icons";
import { Providers } from "./providers";
import { ErrorBox } from "./shell";
import {
  AuditDetailSkeleton,
  AuditHistorySkeleton,
  FindingsSkeleton,
  ProjectDetailSkeleton,
  ProjectsSkeleton,
} from "./skeletons";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("render-only application components", () => {
  it("renders every icon and loading skeleton", () => {
    const { container } = render(
      <>
        <ProjectsIcon data-testid="projects-icon" />
        <FindingsIcon data-testid="findings-icon" />
        <CopyIcon data-testid="copy-icon" />
        <ExternalLinkIcon data-testid="external-icon" />
        <RefreshIcon data-testid="refresh-icon" />
        <ProjectsSkeleton />
        <ProjectDetailSkeleton />
        <AuditHistorySkeleton />
        <AuditDetailSkeleton />
        <FindingsSkeleton />
      </>,
    );

    expect(container.querySelectorAll("svg")).toHaveLength(5);
    expect(screen.getByText("Loading projects")).toBeTruthy();
    expect(screen.getByText("Loading project details")).toBeTruthy();
    expect(screen.getByText("Loading audit history")).toBeTruthy();
    expect(screen.getByText("Loading audit evidence")).toBeTruthy();
    expect(screen.getByText("Searching findings")).toBeTruthy();
  });

  it("wires query and toast providers with a CSP nonce", () => {
    render(
      <Providers nonce="nonce-test">
        <span>Provider child</span>
      </Providers>,
    );

    expect(screen.getByText("Provider child")).toBeTruthy();
    expect(screen.getByRole("region", { name: "Notifications" })).toBeTruthy();
  });
});

describe("error recovery rendering", () => {
  it("copies a support reference and resets the copied state", async () => {
    vi.useFakeTimers();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    const retry = vi.fn();
    render(
      <ErrorBox
        error={
          new ApiError("Rate limited", 429, {
            code: "rate_limited",
            requestId: "req_coverage",
            retryAfter: "5",
          })
        }
        onRetry={retry}
        retryLabel="Retry request"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Copy reference" }));
    await act(async () => Promise.resolve());
    expect(writeText).toHaveBeenCalledWith("req_coverage");
    expect(screen.getByRole("button", { name: "Copied" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry request" }));
    expect(retry).toHaveBeenCalledOnce();
    await act(async () => vi.advanceTimersByTimeAsync(2_000));
    expect(screen.getByRole("button", { name: "Copy reference" })).toBeTruthy();
  });

  it("keeps the copy state safe when clipboard access fails", async () => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
    });
    render(<ErrorBox error={new ApiError("Failed", 500, { requestId: "req_failed" })} />);

    fireEvent.click(screen.getByRole("button", { name: "Copy reference" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Copy reference" })).toBeTruthy(),
    );
  });
});

describe("small shared utilities", () => {
  it("builds every query-key shape", () => {
    expect(queryKeys.projectOptions("acme")).toEqual(["project-options", "acme"]);
    expect(queryKeys.auditOptions("prj")).toEqual(["audit-options", "prj"]);
    expect(queryKeys.project("prj")).toEqual(["project", "prj"]);
    expect(queryKeys.projectAudits("prj")).toEqual(["audits", "prj"]);
    expect(queryKeys.audit("aud")).toEqual(["audit", "aud"]);
    expect(queryKeys.auditStatus("aud")).toEqual(["audit-status", "aud"]);
    expect(queryKeys.auditEvidence("aud")).toEqual(["audit-evidence", "aud"]);
    expect(queryKeys.auditEvidenceKind("aud", "events")).toEqual([
      "audit-evidence",
      "aud",
      "events",
    ]);
    expect(queryKeys.findings({ severity: "high" })).toEqual(["findings", "high", "", "", ""]);
    expect(queryKeys.startAudit("prj")).toEqual(["start-audit", "prj"]);
    expect(queryKeys.updateRecommendation("aud")).toEqual(["update-recommendation", "aud"]);
  });

  it("updates the document title when the title changes", async () => {
    function Title({ value }: { value: string }) {
      usePageTitle(value);
      return null;
    }
    const { rerender } = render(<Title value="Projects" />);
    await waitFor(() => expect(document.title).toBe("Projects | AI Visibility Audit"));
    rerender(<Title value="Findings" />);
    await waitFor(() => expect(document.title).toBe("Findings | AI Visibility Audit"));
  });

  it("covers project validation limits", () => {
    expect(
      validateProjectDraft({ name: "x".repeat(121), domain: "example.com", competitors: "" }).errors
        .name,
    ).toContain("120");
    expect(
      validateProjectDraft({
        name: "Valid",
        domain: "example.com",
        competitors: "not valid",
      }).errors.competitors,
    ).toContain("not a valid");
    expect(
      validateProjectDraft({
        name: "Valid",
        domain: "example.com",
        competitors: Array.from({ length: 11 }, (_, index) => `rival${index}.com`).join(","),
      }).errors.competitors,
    ).toContain("no more than 10");
  });
});
