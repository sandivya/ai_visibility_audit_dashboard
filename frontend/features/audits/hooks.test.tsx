// @vitest-environment jsdom

import { QueryClient, QueryClientProvider, type InfiniteData } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import type { Audit, AuditSummary, CursorPage, Recommendation } from "@/lib/types";
import { useAuditEvidence, useAuditStatus, useStartAudit, useUpdateRecommendation } from "./hooks";

const methodology = {
  mode: "simulated" as const,
  version: "simulated-v2",
  disclosure: "Demo data only.",
  scoring_summary: "Deterministic score.",
  stable_inputs: ["brand", "domain", "competitor set"],
};

const auditSummary: AuditSummary = {
  id: "aud_test",
  status: "queued",
  visibility_score: null,
  created_at: "2026-07-13T00:00:00Z",
  updated_at: "2026-07-13T00:00:00Z",
  methodology,
};

function testClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

function wrapper(client: QueryClient) {
  return function TestWrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("audit query hooks", () => {
  it("fetches every audit evidence collection", async () => {
    const client = testClient();
    const emptyPage = { items: [], next_cursor: null };
    const spies = [
      vi.spyOn(api, "auditPages").mockResolvedValue(emptyPage),
      vi.spyOn(api, "auditPrompts").mockResolvedValue(emptyPage),
      vi.spyOn(api, "auditFindings").mockResolvedValue(emptyPage),
      vi.spyOn(api, "auditRecommendations").mockResolvedValue(emptyPage),
      vi.spyOn(api, "auditEvents").mockResolvedValue(emptyPage),
    ];
    const { result } = renderHook(
      () => ({
        pages: useAuditEvidence("aud_test", "pages"),
        prompts: useAuditEvidence("aud_test", "prompts"),
        findings: useAuditEvidence("aud_test", "findings"),
        recommendations: useAuditEvidence("aud_test", "recommendations"),
        events: useAuditEvidence("aud_test", "events"),
      }),
      { wrapper: wrapper(client) },
    );

    await waitFor(() =>
      expect(Object.values(result.current).every((query) => query.isSuccess)).toBe(true),
    );
    for (const spy of spies) expect(spy).toHaveBeenCalledOnce();
  });

  it("hydrates the first evidence page without an immediate duplicate request", async () => {
    const client = testClient();
    const fetchPages = vi.spyOn(api, "auditPages");
    const firstPage = {
      items: [
        {
          id: "page_1",
          url: "https://example.com",
          title: "Example",
          status_code: 200,
          created_at: "2026-07-13T00:00:00Z",
        },
      ],
      next_cursor: "next",
    };
    const { result, rerender } = renderHook(
      ({ initialPage }: { initialPage?: typeof firstPage }) =>
        useAuditEvidence("aud_test", "pages", {
          enabled: !!initialPage,
          initialPage,
          initialDataUpdatedAt: Date.now(),
        }),
      {
        wrapper: wrapper(client),
        initialProps: { initialPage: undefined as typeof firstPage | undefined },
      },
    );

    rerender({ initialPage: firstPage });
    await waitFor(() => expect(result.current.data?.pages[0]).toEqual(firstPage));
    expect(fetchPages).not.toHaveBeenCalled();
  });

  it("retains one idempotency key until audit creation succeeds", async () => {
    const client = testClient();
    const firstKey = "00000000-0000-4000-8000-000000000001";
    const secondKey = "00000000-0000-4000-8000-000000000002";
    vi.spyOn(globalThis.crypto, "randomUUID")
      .mockReturnValueOnce(firstKey)
      .mockReturnValueOnce(secondKey);
    const start = vi
      .spyOn(api, "startAudit")
      .mockRejectedValueOnce(new ApiError("Temporarily unavailable", 503))
      .mockResolvedValue(auditSummary);
    const { result } = renderHook(() => useStartAudit("prj_test"), { wrapper: wrapper(client) });

    await act(async () => {
      await expect(result.current.mutateAsync()).rejects.toThrow("Temporarily unavailable");
    });
    await act(async () => {
      await result.current.mutateAsync();
    });
    await act(async () => {
      await result.current.mutateAsync();
    });

    expect(start.mock.calls.map((call) => call[1])).toEqual([firstKey, firstKey, secondKey]);
  });

  it("rolls back an optimistic recommendation status after a failed save", async () => {
    const client = testClient();
    const recommendation: Recommendation = {
      id: "rec_test",
      audit_id: "aud_test",
      priority: "high",
      title: "Improve citations",
      description: "Add authoritative supporting sources.",
      status: "open",
      evidence_kind: "prompts",
      related_finding_id: null,
      related_finding_category: null,
      created_at: "2026-07-13T00:00:00Z",
      updated_at: "2026-07-13T00:00:00Z",
    };
    const audit: Audit = {
      ...auditSummary,
      project_id: "prj_test",
      error_message: null,
      retryable: false,
      failure_kind: null,
      pages: [],
      prompts: [],
      findings: [],
      recommendations: [recommendation],
      events: [],
      page_count: 0,
      prompt_count: 0,
      finding_count: 0,
      recommendation_count: 1,
      event_count: 0,
      pages_next_cursor: null,
      prompts_next_cursor: null,
      findings_next_cursor: null,
      recommendations_next_cursor: null,
      events_next_cursor: null,
    };
    const evidence: InfiniteData<CursorPage<Recommendation>> = {
      pages: [{ items: [recommendation], next_cursor: null }],
      pageParams: [null],
    };
    client.setQueryData(queryKeys.audit("aud_test"), audit);
    client.setQueryData(queryKeys.auditEvidenceKind("aud_test", "recommendations"), evidence);
    let rejectSave!: (error: Error) => void;
    const pendingSave = new Promise<Recommendation>((_resolve, reject) => {
      rejectSave = reject;
    });
    vi.spyOn(api, "updateRecommendation").mockReturnValue(pendingSave);
    const { result } = renderHook(() => useUpdateRecommendation("aud_test"), {
      wrapper: wrapper(client),
    });

    act(() => result.current.mutate({ recommendationId: "rec_test", status: "completed" }));
    await waitFor(() =>
      expect(
        client.getQueryData<Audit>(queryKeys.audit("aud_test"))?.recommendations[0].status,
      ).toBe("completed"),
    );
    act(() => rejectSave(new Error("Save failed")));
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(client.getQueryData<Audit>(queryKeys.audit("aud_test"))?.recommendations[0].status).toBe(
      "open",
    );
    expect(
      client.getQueryData<InfiniteData<CursorPage<Recommendation>>>(
        queryKeys.auditEvidenceKind("aud_test", "recommendations"),
      )?.pages[0].items[0].status,
    ).toBe("open");
  });

  it("invalidates audit, evidence, project, and list caches at a terminal state", async () => {
    const client = testClient();
    vi.spyOn(api, "auditStatus").mockResolvedValue({
      id: "aud_test",
      project_id: "prj_test",
      status: "completed",
      visibility_score: 82,
      error_message: null,
      retryable: false,
      failure_kind: null,
      updated_at: "2026-07-13T00:01:00Z",
    });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(
      () =>
        useAuditStatus("aud_test", { status: "processing", updated_at: "2026-07-13T00:00:30Z" }),
      { wrapper: wrapper(client) },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    await waitFor(() =>
      expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.audit("aud_test") }),
    );

    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.auditEvidence("aud_test") });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.project("prj_test") });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.projectAudits("prj_test") });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.projects });
  });

  it("does not refetch hydrated evidence for an already-synchronized terminal audit", async () => {
    const client = testClient();
    const terminal = {
      id: "aud_test",
      project_id: "prj_test",
      status: "completed" as const,
      visibility_score: 82,
      error_message: null,
      retryable: false,
      failure_kind: null,
      updated_at: "2026-07-13T00:01:00Z",
    };
    vi.spyOn(api, "auditStatus").mockResolvedValue(terminal);
    const invalidate = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useAuditStatus("aud_test", terminal), {
      wrapper: wrapper(client),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("waits for the detail snapshot before invalidating a direct terminal status", async () => {
    const client = testClient();
    vi.spyOn(api, "auditStatus").mockResolvedValue({
      id: "aud_test",
      project_id: "prj_test",
      status: "completed",
      visibility_score: 82,
      error_message: null,
      retryable: false,
      failure_kind: null,
      updated_at: "2026-07-13T00:01:00Z",
    });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useAuditStatus("aud_test"), {
      wrapper: wrapper(client),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("handles recommendation failures without cached context and applies server success", async () => {
    const client = testClient();
    const updated: Recommendation = {
      id: "rec_test",
      audit_id: "aud_test",
      priority: "high",
      title: "Improve citations",
      description: "Add authoritative supporting sources.",
      status: "completed",
      evidence_kind: "prompts",
      related_finding_id: null,
      related_finding_category: null,
      created_at: "2026-07-13T00:00:00Z",
      updated_at: "2026-07-13T00:01:00Z",
    };
    const update = vi
      .spyOn(api, "updateRecommendation")
      .mockRejectedValueOnce(new Error("No cache failure"))
      .mockResolvedValueOnce(updated);
    const { result } = renderHook(() => useUpdateRecommendation("aud_test"), {
      wrapper: wrapper(client),
    });

    await act(async () => {
      await expect(
        result.current.mutateAsync({ recommendationId: "rec_test", status: "completed" }),
      ).rejects.toThrow("No cache failure");
    });
    await act(async () => {
      await result.current.mutateAsync({ recommendationId: "rec_test", status: "completed" });
    });

    expect(update).toHaveBeenCalledTimes(2);
  });
});
