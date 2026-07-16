import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

describe("audit API mutations", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("passes the caller-owned idempotency key when starting an audit", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "aud_123",
          status: "queued",
          visibility_score: null,
          created_at: "2026-07-13T00:00:00Z",
          updated_at: "2026-07-13T00:00:00Z",
        }),
        { status: 202, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await api.startAudit("prj_123", "intent-key-123");

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/api/projects/prj_123/audits");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("Idempotency-Key")).toBe("intent-key-123");
  });

  it("preserves backend error metadata for recovery and support", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          error: {
            code: "rate_limited",
            message: "Too many audit requests",
            request_id: "req_123",
          },
        }),
        {
          status: 429,
          headers: { "Content-Type": "application/json", "Retry-After": "12" },
        },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.me()).rejects.toEqual(
      expect.objectContaining({
        message: "Too many audit requests",
        status: 429,
        code: "rate_limited",
        requestId: "req_123",
        retryAfter: "12",
      }),
    );
  });

  it("sends project search terms with cursor pagination", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], next_cursor: null }), {
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await api.projects("next-page", 20, "Acme Labs");

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      "http://localhost:8000/api/projects?limit=20&cursor=next-page&search=Acme+Labs",
    );
  });

  it("cancels requests that exceed the default timeout", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockImplementation(
      (_url: string, init: RequestInit) =>
        new Promise((_resolve, reject) => {
          init.signal?.addEventListener(
            "abort",
            () => reject(new DOMException("Aborted", "AbortError")),
            { once: true },
          );
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const assertion = expect(api.me()).rejects.toEqual(
      expect.objectContaining({
        status: 408,
        code: "request_timeout",
      }),
    );
    await vi.advanceTimersByTimeAsync(15_000);
    await assertion;
  });

  it("exercises every API wrapper and request shape", async () => {
    const fetchMock = vi.fn().mockImplementation((_url: string, init?: RequestInit) =>
      Promise.resolve(
        init?.method === "DELETE"
          ? new Response(null, { status: 204 })
          : new Response(JSON.stringify({ items: [], next_cursor: null }), {
              headers: { "Content-Type": "application/json" },
            }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const signal = new AbortController().signal;

    expect(api.oidcLoginUrl()).toBe("http://localhost:8000/api/auth/oidc/login");
    await api.authConfig(signal);
    await api.loginUsers(signal);
    await api.login("usr_test");
    await api.logout();
    await api.me(signal);
    await api.projects(null, 10, "   ", signal);
    await api.project("prj_test", signal);
    await api.createProject({ name: "Test", domain: "test.example", competitors: [] });
    await api.audits("prj_test", "cursor", 5, signal);
    await api.audit("aud_test", signal);
    await api.auditStatus("aud_test", signal);
    await api.auditPages("aud_test", "cursor", signal);
    await api.auditPrompts("aud_test", "cursor", signal);
    await api.auditFindings("aud_test", "cursor", signal);
    await api.auditRecommendations("aud_test", "cursor", signal);
    await api.auditEvents("aud_test", "cursor", signal);
    await api.updateRecommendation("rec_test", "dismissed");
    await api.findings(
      {
        severity: "high",
        category: "ai_visibility",
        project_id: "prj_test",
        audit_id: "aud_test",
        cursor: "cursor",
      },
      signal,
    );

    expect(fetchMock).toHaveBeenCalledTimes(18);
  });

  it("propagates an already-aborted caller signal", async () => {
    const controller = new AbortController();
    controller.abort("caller cancelled");
    const fetchMock = vi.fn().mockImplementation((_url: string, init: RequestInit) => {
      expect(init.signal?.aborted).toBe(true);
      return Promise.reject(new DOMException("Aborted", "AbortError"));
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.me(controller.signal)).rejects.toThrow("Aborted");
  });

  it("falls back to safe metadata when an error response is not JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("not-json", {
          status: 502,
          headers: { "X-Request-Id": "req_header" },
        }),
      ),
    );

    await expect(api.me()).rejects.toEqual(
      expect.objectContaining({
        message: "The request could not be completed",
        code: "http_502",
        requestId: "req_header",
      }),
    );
  });
});
