import type {
  Audit,
  AuditEvent,
  AuditPageEvidence,
  AuditPromptEvidence,
  AuditStatusDetail,
  AuthConfig,
  AuditSummary,
  CursorPage,
  Finding,
  Project,
  Recommendation,
  RecommendationStatus,
  User,
} from "./types";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const configuredTimeout = Number(process.env.NEXT_PUBLIC_API_TIMEOUT_MS);
const REQUEST_TIMEOUT_MS =
  Number.isFinite(configuredTimeout) && configuredTimeout > 0 ? configuredTimeout : 15_000;

type ApiErrorMetadata = {
  code?: string;
  requestId?: string | null;
  retryAfter?: string | null;
};

export class ApiError extends Error {
  public readonly code: string;
  public readonly requestId: string | null;
  public readonly retryAfter: string | null;

  constructor(
    message: string,
    public readonly status: number,
    metadata: ApiErrorMetadata = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.code = metadata.code ?? `http_${status}`;
    this.requestId = metadata.requestId ?? null;
    this.retryAfter = metadata.retryAfter ?? null;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const controller = new AbortController();
  const upstreamSignal = init?.signal;
  let timedOut = false;
  const timeout = globalThis.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, REQUEST_TIMEOUT_MS);
  const cancelFromUpstream = () => controller.abort(upstreamSignal?.reason);
  if (upstreamSignal?.aborted) cancelFromUpstream();
  else upstreamSignal?.addEventListener("abort", cancelFromUpstream, { once: true });

  try {
    const response = await fetch(`${API}/api${path}`, {
      ...init,
      credentials: "include",
      headers,
      signal: controller.signal,
    });
    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as {
        error?: { code?: string; message?: string; request_id?: string };
      } | null;
      throw new ApiError(
        body?.error?.message ?? "The request could not be completed",
        response.status,
        {
          code: body?.error?.code,
          requestId: body?.error?.request_id ?? response.headers.get("X-Request-Id"),
          retryAfter: response.headers.get("Retry-After"),
        },
      );
    }
    if (response.status === 204) return undefined as T;
    return response.json();
  } catch (error) {
    if (timedOut) {
      throw new ApiError("The request timed out. Check your connection and try again.", 408, {
        code: "request_timeout",
      });
    }
    throw error;
  } finally {
    globalThis.clearTimeout(timeout);
    upstreamSignal?.removeEventListener("abort", cancelFromUpstream);
  }
}

function cursorQuery(cursor?: string | null, limit = 20, search?: string) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor) params.set("cursor", cursor);
  if (search?.trim()) params.set("search", search.trim());
  return params.toString();
}

export const api = {
  authConfig: (signal?: AbortSignal) => request<AuthConfig>("/auth/config", { signal }),
  oidcLoginUrl: () => `${API}/api/auth/oidc/login`,
  loginUsers: (signal?: AbortSignal) => request<User[]>("/auth/users", { signal }),
  login: (userId: string) =>
    request<User>("/auth/sessions", { method: "POST", body: JSON.stringify({ user_id: userId }) }),
  logout: () => request<void>("/auth/sessions", { method: "DELETE" }),
  me: (signal?: AbortSignal) => request<User>("/auth/me", { signal }),
  projects: (cursor?: string | null, limit = 20, search?: string, signal?: AbortSignal) =>
    request<CursorPage<Project>>(`/projects?${cursorQuery(cursor, limit, search)}`, { signal }),
  project: (id: string, signal?: AbortSignal) => request<Project>(`/projects/${id}`, { signal }),
  createProject: (body: { name: string; domain: string; competitors: string[] }) =>
    request<Project>("/projects", { method: "POST", body: JSON.stringify(body) }),
  audits: (projectId: string, cursor?: string | null, limit = 20, signal?: AbortSignal) =>
    request<CursorPage<AuditSummary>>(
      `/projects/${projectId}/audits?${cursorQuery(cursor, limit)}`,
      { signal },
    ),
  audit: (id: string, signal?: AbortSignal) => request<Audit>(`/audits/${id}`, { signal }),
  auditStatus: (id: string, signal?: AbortSignal) =>
    request<AuditStatusDetail>(`/audits/${id}/status`, { signal }),
  auditPages: (id: string, cursor?: string | null, signal?: AbortSignal) =>
    request<CursorPage<AuditPageEvidence>>(`/audits/${id}/pages?${cursorQuery(cursor)}`, {
      signal,
    }),
  auditPrompts: (id: string, cursor?: string | null, signal?: AbortSignal) =>
    request<CursorPage<AuditPromptEvidence>>(`/audits/${id}/prompts?${cursorQuery(cursor)}`, {
      signal,
    }),
  auditFindings: (id: string, cursor?: string | null, signal?: AbortSignal) =>
    request<CursorPage<Finding>>(`/audits/${id}/findings?${cursorQuery(cursor)}`, { signal }),
  auditRecommendations: (id: string, cursor?: string | null, signal?: AbortSignal) =>
    request<CursorPage<Recommendation>>(`/audits/${id}/recommendations?${cursorQuery(cursor)}`, {
      signal,
    }),
  auditEvents: (id: string, cursor?: string | null, signal?: AbortSignal) =>
    request<CursorPage<AuditEvent>>(`/audits/${id}/events?${cursorQuery(cursor)}`, { signal }),
  startAudit: (projectId: string, idempotencyKey: string) =>
    request<AuditSummary>(`/projects/${projectId}/audits`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
    }),
  updateRecommendation: (id: string, status: RecommendationStatus) =>
    request<Recommendation>(`/recommendations/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),
  findings: (
    filters: {
      severity?: string;
      category?: string;
      audit_id?: string;
      project_id?: string;
      cursor?: string | null;
    },
    signal?: AbortSignal,
  ) => {
    const params = new URLSearchParams({ limit: "20" });
    Object.entries(filters).forEach(([key, value]) => {
      if (value) params.set(key, value);
    });
    return request<CursorPage<Finding>>(`/findings?${params.toString()}`, { signal });
  },
};
