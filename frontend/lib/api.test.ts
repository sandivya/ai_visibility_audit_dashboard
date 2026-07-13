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
});
