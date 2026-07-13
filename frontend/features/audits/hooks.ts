"use client";

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
} from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { api, ApiError } from "@/lib/api";
import { queryKeys, type AuditEvidenceKind } from "@/lib/query-keys";
import type {
  Audit,
  AuditEvent,
  AuditPageEvidence,
  AuditPromptEvidence,
  AuditStatus,
  AuditSummary,
  CursorPage,
  Finding,
  Recommendation,
  RecommendationStatus,
} from "@/lib/types";

const AUDIT_STATUS_POLL_INTERVAL_MS = 2_000;
const ACTIVE_AUDIT_STATUSES = new Set<AuditStatus>(["queued", "processing"]);
const TERMINAL_AUDIT_STATUSES = new Set<AuditStatus>(["completed", "failed"]);

type AuditEvidenceMap = {
  pages: AuditPageEvidence;
  prompts: AuditPromptEvidence;
  findings: Finding;
  recommendations: Recommendation;
  events: AuditEvent;
};

type StartAuditOptions = {
  onSuccess?: (audit: AuditSummary) => void;
};

export type UpdateRecommendationVariables = {
  recommendationId: string;
  status: RecommendationStatus;
};

type RecommendationMutationContext = {
  audit?: Audit;
  recommendations?: InfiniteData<CursorPage<Recommendation>>;
};

async function fetchAuditEvidence<Kind extends AuditEvidenceKind>(
  auditId: string,
  kind: Kind,
  cursor: string | null,
  signal?: AbortSignal,
): Promise<CursorPage<AuditEvidenceMap[Kind]>> {
  switch (kind) {
    case "pages":
      return api.auditPages(auditId, cursor, signal) as Promise<CursorPage<AuditEvidenceMap[Kind]>>;
    case "prompts":
      return api.auditPrompts(auditId, cursor, signal) as Promise<
        CursorPage<AuditEvidenceMap[Kind]>
      >;
    case "findings":
      return api.auditFindings(auditId, cursor, signal) as Promise<
        CursorPage<AuditEvidenceMap[Kind]>
      >;
    case "recommendations":
      return api.auditRecommendations(auditId, cursor, signal) as Promise<
        CursorPage<AuditEvidenceMap[Kind]>
      >;
    case "events":
      return api.auditEvents(auditId, cursor, signal) as Promise<
        CursorPage<AuditEvidenceMap[Kind]>
      >;
  }
}

function updateAuditRecommendation(
  current: Audit | undefined,
  recommendationId: string,
  update: (recommendation: Recommendation) => Recommendation,
) {
  if (!current) return current;
  return {
    ...current,
    recommendations: current.recommendations.map((recommendation) =>
      recommendation.id === recommendationId ? update(recommendation) : recommendation,
    ),
  };
}

function updateEvidenceRecommendation(
  current: InfiniteData<CursorPage<Recommendation>> | undefined,
  recommendationId: string,
  update: (recommendation: Recommendation) => Recommendation,
) {
  if (!current) return current;
  return {
    ...current,
    pages: current.pages.map((page) => ({
      ...page,
      items: page.items.map((recommendation) =>
        recommendation.id === recommendationId ? update(recommendation) : recommendation,
      ),
    })),
  };
}

/** Polls only while work is active and refreshes related views once terminal. */
export function useAuditStatus(
  auditId: string,
  auditSnapshot?: Pick<Audit, "status" | "updated_at">,
) {
  const queryClient = useQueryClient();
  const lastInvalidatedTerminal = useRef<string | null>(null);
  const query = useQuery({
    queryKey: queryKeys.auditStatus(auditId),
    queryFn: ({ signal }) => api.auditStatus(auditId, signal),
    enabled: Boolean(auditId),
    refetchInterval: ({ state }) =>
      state.data && ACTIVE_AUDIT_STATUSES.has(state.data.status)
        ? AUDIT_STATUS_POLL_INTERVAL_MS
        : false,
    refetchIntervalInBackground: false,
  });

  useEffect(() => {
    const status = query.data;
    if (!status || !TERMINAL_AUDIT_STATUSES.has(status.status)) return;

    const terminalVersion = `${auditId}:${status.status}:${status.updated_at}`;
    if (lastInvalidatedTerminal.current === terminalVersion) return;

    // A direct visit to an already-terminal audit hydrates every evidence query
    // from the detail response. Wait for that detail snapshot and avoid turning
    // the first lightweight status response into six duplicate network requests.
    if (!auditSnapshot) return;
    if (auditSnapshot.status === status.status && auditSnapshot.updated_at === status.updated_at) {
      lastInvalidatedTerminal.current = terminalVersion;
      return;
    }

    lastInvalidatedTerminal.current = terminalVersion;

    void Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.audit(auditId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.auditEvidence(auditId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.projects }),
      queryClient.invalidateQueries({ queryKey: queryKeys.project(status.project_id) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.projectAudits(status.project_id) }),
    ]);
  }, [auditId, auditSnapshot, query.data, queryClient]);

  return query;
}

/** Shared cursor behavior for the five audit evidence collections. */
export function useAuditEvidence<Kind extends AuditEvidenceKind>(
  auditId: string,
  kind: Kind,
  options: {
    enabled?: boolean;
    initialPage?: CursorPage<AuditEvidenceMap[Kind]>;
    initialDataUpdatedAt?: number;
  } = {},
) {
  return useInfiniteQuery({
    queryKey: queryKeys.auditEvidenceKind(auditId, kind),
    queryFn: ({ pageParam, signal }) => fetchAuditEvidence(auditId, kind, pageParam, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    enabled: Boolean(auditId) && (options.enabled ?? true),
    initialData: options.initialPage
      ? { pages: [options.initialPage], pageParams: [null] }
      : undefined,
    initialDataUpdatedAt: options.initialDataUpdatedAt,
    staleTime: options.initialPage ? 30_000 : 0,
  });
}

/**
 * Keeps one idempotency key across automatic and user-initiated retries until
 * an audit is successfully accepted. A later audit intent receives a new key.
 */
export function useStartAudit(projectId: string, options: StartAuditOptions = {}) {
  const queryClient = useQueryClient();
  const idempotencyKey = useRef<string | null>(null);

  return useMutation({
    mutationKey: queryKeys.startAudit(projectId),
    retry: (failureCount, error) => !(error instanceof ApiError) && failureCount < 1,
    mutationFn: () => {
      idempotencyKey.current ??= crypto.randomUUID();
      return api.startAudit(projectId, idempotencyKey.current);
    },
    onSuccess: (audit) => {
      idempotencyKey.current = null;
      void queryClient.invalidateQueries({ queryKey: queryKeys.projectAudits(projectId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.project(projectId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects });
      options.onSuccess?.(audit);
    },
  });
}

/** Optimistically updates both summary and paginated recommendation caches. */
export function useUpdateRecommendation(auditId: string) {
  const queryClient = useQueryClient();
  const evidenceKey = queryKeys.auditEvidenceKind(auditId, "recommendations");

  return useMutation<
    Recommendation,
    Error,
    UpdateRecommendationVariables,
    RecommendationMutationContext
  >({
    mutationKey: queryKeys.updateRecommendation(auditId),
    mutationFn: ({ recommendationId, status }) =>
      api.updateRecommendation(recommendationId, status),
    onMutate: async ({ recommendationId, status }) => {
      await Promise.all([
        queryClient.cancelQueries({ queryKey: queryKeys.audit(auditId) }),
        queryClient.cancelQueries({ queryKey: evidenceKey }),
      ]);

      const context: RecommendationMutationContext = {
        audit: queryClient.getQueryData<Audit>(queryKeys.audit(auditId)),
        recommendations:
          queryClient.getQueryData<InfiniteData<CursorPage<Recommendation>>>(evidenceKey),
      };
      const optimisticUpdate = (recommendation: Recommendation): Recommendation => ({
        ...recommendation,
        status,
      });

      queryClient.setQueryData<Audit>(queryKeys.audit(auditId), (current) =>
        updateAuditRecommendation(current, recommendationId, optimisticUpdate),
      );
      queryClient.setQueryData<InfiniteData<CursorPage<Recommendation>>>(evidenceKey, (current) =>
        updateEvidenceRecommendation(current, recommendationId, optimisticUpdate),
      );
      return context;
    },
    onError: (_error, _variables, context) => {
      if (!context) return;
      queryClient.setQueryData(queryKeys.audit(auditId), context.audit);
      queryClient.setQueryData(evidenceKey, context.recommendations);
    },
    onSuccess: (updated) => {
      const serverUpdate = () => updated;
      queryClient.setQueryData<Audit>(queryKeys.audit(auditId), (current) =>
        updateAuditRecommendation(current, updated.id, serverUpdate),
      );
      queryClient.setQueryData<InfiniteData<CursorPage<Recommendation>>>(evidenceKey, (current) =>
        updateEvidenceRecommendation(current, updated.id, serverUpdate),
      );
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: evidenceKey });
    },
  });
}
