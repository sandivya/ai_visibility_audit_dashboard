"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { FindingCard } from "@/components/finding-card";
import { CopyIcon, ExternalLinkIcon, RefreshIcon } from "@/components/icons";
import { LoadMoreButton } from "@/components/load-more-button";
import { ErrorBox, Score, Shell, Status } from "@/components/shell";
import { AuditDetailSkeleton } from "@/components/skeletons";
import { useToast } from "@/components/toast";
import { useAuditEvidence, useAuditStatus, useStartAudit } from "@/features/audits/hooks";
import { RecommendationCard } from "@/features/audits/recommendation-card";
import {
  auditEvidenceAnchor,
  isAuditFinalizing,
  safeEvidenceUrl,
  scoreNarrative,
  summarizeAuditEvidence,
} from "@/features/audits/view-model";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { usePageTitle } from "@/lib/use-page-title";

function EvidenceUrl({ url }: { url: string }) {
  const safeUrl = safeEvidenceUrl(url);

  return safeUrl ? (
    <a className="evidence-url" href={safeUrl} target="_blank" rel="noreferrer noopener">
      {url}
      <ExternalLinkIcon />
    </a>
  ) : (
    <span className="evidence-url-invalid">{url}</span>
  );
}

export default function AuditPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { showToast } = useToast();
  const [copyState, setCopyState] = useState<"idle" | "copied">("idle");
  const session = useQuery({
    queryKey: queryKeys.session,
    queryFn: ({ signal }) => api.me(signal),
    retry: false,
  });
  const audit = useQuery({
    queryKey: queryKeys.audit(id),
    queryFn: ({ signal }) => api.audit(id, signal),
  });
  const status = useAuditStatus(id, audit.data);
  const base = audit.data;
  const initialDataUpdatedAt = audit.dataUpdatedAt || undefined;
  const pages = useAuditEvidence(id, "pages", {
    enabled: !!base,
    initialPage: base ? { items: base.pages, next_cursor: base.pages_next_cursor } : undefined,
    initialDataUpdatedAt,
  });
  const prompts = useAuditEvidence(id, "prompts", {
    enabled: !!base,
    initialPage: base ? { items: base.prompts, next_cursor: base.prompts_next_cursor } : undefined,
    initialDataUpdatedAt,
  });
  const findings = useAuditEvidence(id, "findings", {
    enabled: !!base,
    initialPage: base
      ? { items: base.findings, next_cursor: base.findings_next_cursor }
      : undefined,
    initialDataUpdatedAt,
  });
  const recommendations = useAuditEvidence(id, "recommendations", {
    enabled: !!base,
    initialPage: base
      ? { items: base.recommendations, next_cursor: base.recommendations_next_cursor }
      : undefined,
    initialDataUpdatedAt,
  });
  const events = useAuditEvidence(id, "events", {
    enabled: !!base,
    initialPage: base ? { items: base.events, next_cursor: base.events_next_cursor } : undefined,
    initialDataUpdatedAt,
  });
  const retryAudit = useStartAudit(base?.project_id ?? "", {
    onSuccess: (newAudit) => {
      showToast({
        title: "New audit queued",
        description: "The replacement audit is ready to track.",
        tone: "success",
      });
      router.replace(`/audits/${newAudit.id}`);
    },
  });

  usePageTitle(`Audit ${id.slice(-8)}`);

  const data = base && status.data ? { ...base, ...status.data } : base;
  const pageRows = pages.data?.pages.flatMap((page) => page.items) ?? base?.pages ?? [];
  const promptRows = prompts.data?.pages.flatMap((page) => page.items) ?? base?.prompts ?? [];
  const findingRows = findings.data?.pages.flatMap((page) => page.items) ?? base?.findings ?? [];
  const recommendationRows =
    recommendations.data?.pages.flatMap((page) => page.items) ?? base?.recommendations ?? [];
  const eventRows = events.data?.pages.flatMap((page) => page.items) ?? base?.events ?? [];
  const canWrite = session.data?.role !== "viewer";
  const isActive = data?.status === "queued" || data?.status === "processing";
  const isCompleted = data?.status === "completed";
  const evidenceIsRefreshing = [pages, prompts, findings, recommendations, events].some(
    (query) => query.isFetching,
  );
  const isFinalizing = isAuditFinalizing(base, status.data, {
    auditIsFetching: audit.isFetching,
    evidenceIsRefreshing,
  });
  const evidenceError =
    pages.error || prompts.error || findings.error || recommendations.error || events.error;
  const { brandMentions, mentionRate, uniqueCompetitors, severityCounts, pageHealthRate } =
    summarizeAuditEvidence(promptRows, findingRows, pageRows);

  async function copyAuditId() {
    try {
      await navigator.clipboard.writeText(id);
      setCopyState("copied");
      globalThis.setTimeout(() => setCopyState("idle"), 2_000);
    } catch {
      showToast({
        title: "Couldn’t copy audit ID",
        description: "Select the full identifier and copy it manually.",
        tone: "error",
      });
    }
  }

  function refreshEvidence() {
    void Promise.all([
      pages.refetch(),
      prompts.refetch(),
      findings.refetch(),
      recommendations.refetch(),
      events.refetch(),
    ]);
  }

  return (
    <Shell>
      <header className="topbar audit-topbar">
        <div>
          <Link href={data ? `/projects/${data.project_id}` : "/"} className="back">
            ← Project
          </Link>
          <div className="title-line">
            <h1>Audit detail</h1>
            {data && <Status value={data.status} />}
          </div>
          <div className="audit-identity">
            <span>Audit ID</span>
            <code>{id}</code>
            <button
              className="copy-button"
              type="button"
              onClick={() => void copyAuditId()}
              aria-label={`Copy full audit ID ${id}`}
            >
              <CopyIcon />
              {copyState === "copied" ? "Copied" : "Copy"}
            </button>
            <span className="sr-only" aria-live="polite">
              {copyState === "copied" ? "Audit ID copied" : ""}
            </span>
          </div>
        </div>
      </header>
      <section className="content">
        {audit.isLoading && <AuditDetailSkeleton />}
        {audit.error && <ErrorBox error={audit.error} onRetry={() => void audit.refetch()} />}
        {status.error && data && (
          <ErrorBox
            message={`Live status could not be refreshed. ${status.error.message}`}
            error={status.error}
            onRetry={() => void status.refetch()}
          />
        )}
        {evidenceError && data && (
          <ErrorBox
            message={`Some audit evidence could not be refreshed. ${evidenceError.message}`}
            error={evidenceError}
            onRetry={refreshEvidence}
            retryLabel="Refresh evidence"
          />
        )}
        {retryAudit.error && (
          <ErrorBox
            error={retryAudit.error}
            onRetry={() => retryAudit.mutate()}
            retryLabel="Retry audit"
          />
        )}
        {data && (
          <>
            <p className="sr-only" aria-live="polite">
              Audit status: {isFinalizing ? "finalizing results" : data.status.replace("_", " ")}
            </p>
            {(isActive || isFinalizing) && (
              <div className="progress-card" role="status" aria-live="polite">
                <div className="spinner" aria-hidden="true" />
                <div className="progress-copy">
                  <h2>
                    {isFinalizing
                      ? "Finalizing results"
                      : data.status === "queued"
                        ? "Audit queued"
                        : "Analyzing visibility signals"}
                  </h2>
                  <p>
                    {isFinalizing
                      ? "Analysis is complete. We’re synchronizing the final evidence and recommendations before declaring the result ready."
                      : data.status === "queued"
                        ? "Your audit is next in line. Analysis will start automatically."
                        : "We’re reviewing pages and AI visibility signals. Results will appear automatically."}
                  </p>
                </div>
              </div>
            )}
            {data.status === "failed" && (
              <div className="failure-panel">
                <ErrorBox message={data.error_message ?? "Audit processing failed"} />
                {data.failure_kind === "deterministic_demo" && (
                  <p className="failure-guidance">
                    This demo failure is tied to the project inputs. Running the unchanged project
                    again would repeat the same result; create a project with a corrected domain
                    instead.
                  </p>
                )}
                <div className="failure-actions">
                  {canWrite && data.retryable && (
                    <button
                      type="button"
                      onClick={() => retryAudit.mutate()}
                      disabled={retryAudit.isPending}
                    >
                      <RefreshIcon />
                      {retryAudit.isPending ? "Starting replacement…" : "Retry audit"}
                    </button>
                  )}
                  {canWrite && !data.retryable && (
                    <Link className="button-link" href="/?create=1">
                      Create corrected project
                    </Link>
                  )}
                  <Link className="button-link secondary" href={`/projects/${data.project_id}`}>
                    Return to project
                  </Link>
                </div>
              </div>
            )}

            <aside className="methodology-panel" aria-labelledby="audit-methodology-title">
              <div className="methodology-heading">
                <div>
                  <p className="eyebrow">Methodology</p>
                  <h2 id="audit-methodology-title">Simulated demo audit</h2>
                </div>
                <span>{data.methodology.version}</span>
              </div>
              <p>{data.methodology.disclosure}</p>
              <p className="methodology-score">{data.methodology.scoring_summary}</p>
            </aside>

            <nav className="audit-jump-nav" aria-label="Audit result sections">
              <span>Jump to</span>
              <a href="#visibility-insights">Visibility insights</a>
              <a href="#findings">Findings</a>
              <a href="#recommendations">Actions</a>
              <a href="#page-evidence">Evidence</a>
              <a href="#audit-timeline">Timeline</a>
            </nav>

            <div className="audit-summary">
              <div>
                <p className="eyebrow">Visibility score</p>
                <Score value={data.visibility_score} />
              </div>
              <div>
                <span>Pages analyzed</span>
                <strong>{data.page_count}</strong>
              </div>
              <div>
                <span>Prompts checked</span>
                <strong>{data.prompt_count}</strong>
              </div>
              <div>
                <span>Created</span>
                <strong>{new Date(data.created_at).toLocaleString()}</strong>
              </div>
              <div>
                <span>Last updated</span>
                <strong>{new Date(data.updated_at).toLocaleString()}</strong>
              </div>
            </div>

            <section
              className="visibility-insights"
              id="visibility-insights"
              aria-labelledby="visibility-insights-title"
            >
              <div className="insight-heading">
                <div>
                  <p className="eyebrow">Evidence snapshot</p>
                  <h2 id="visibility-insights-title">What is driving visibility</h2>
                </div>
                <p>{scoreNarrative(data.visibility_score)}</p>
              </div>
              <div className="insight-metrics">
                <div>
                  <span>Mention rate</span>
                  <strong>{mentionRate === null ? "—" : `${mentionRate}%`}</strong>
                  <small>
                    {promptRows.length
                      ? `${brandMentions} of ${promptRows.length} loaded prompts`
                      : "Awaiting prompt evidence"}
                  </small>
                </div>
                <div>
                  <span>Brand mentions</span>
                  <strong>{brandMentions}</strong>
                  <small>Prompts where the brand appeared</small>
                </div>
                <div>
                  <span>Competitors surfaced</span>
                  <strong>{uniqueCompetitors}</strong>
                  <small>Unique brands in loaded prompts</small>
                </div>
                <div>
                  <span>Finding severity</span>
                  <div className="severity-breakdown">
                    <span className="high">{severityCounts.high} high</span>
                    <span className="medium">{severityCounts.medium} medium</span>
                    <span className="low">{severityCounts.low} low</span>
                  </div>
                  <small>Across loaded diagnostic findings</small>
                </div>
              </div>
              <div className="driver-cues">
                <strong>Score driver cues</strong>
                <div>
                  {mentionRate !== null && (
                    <a
                      href="#prompt-evidence"
                      className={mentionRate >= 60 ? "positive" : "attention"}
                    >
                      {mentionRate}% prompt coverage
                    </a>
                  )}
                  {pageHealthRate !== null && (
                    <a
                      href="#page-evidence"
                      className={pageHealthRate >= 90 ? "positive" : "attention"}
                    >
                      {pageHealthRate}% healthy page responses
                    </a>
                  )}
                  <a
                    href="#findings"
                    className={severityCounts.high === 0 ? "positive" : "attention"}
                  >
                    {severityCounts.high
                      ? `${severityCounts.high} high-priority gaps`
                      : "No high-priority gaps loaded"}
                  </a>
                  {uniqueCompetitors > 0 && (
                    <a href="#prompt-evidence" className="neutral">
                      {uniqueCompetitors} competitors surfaced
                    </a>
                  )}
                </div>
                <p>
                  These cues summarize visible evidence; they explain the result without
                  representing the complete scoring formula.
                </p>
              </div>
            </section>

            <div className="results-grid">
              <section id="findings" aria-labelledby="findings-title">
                <div className="section-heading">
                  <div>
                    <p className="eyebrow">Diagnostic layer</p>
                    <h2 id="findings-title">Findings</h2>
                  </div>
                  <Link href={`/findings?project_id=${data.project_id}&audit_id=${data.id}`}>
                    Open filtered view →
                  </Link>
                </div>
                {findingRows.map((item) => (
                  <FindingCard
                    item={item}
                    evidenceHref={auditEvidenceAnchor(item.evidence_kind)}
                    key={item.id}
                  />
                ))}
                {findingRows.length === 0 && !findings.error && (
                  <div className="section-empty">
                    <p>
                      {isCompleted && !isFinalizing
                        ? "This audit completed without findings."
                        : "Findings will appear when final analysis is ready."}
                    </p>
                  </div>
                )}
                {findings.hasNextPage && (
                  <LoadMoreButton
                    fullWidth
                    isLoading={findings.isFetchingNextPage}
                    onLoad={() => void findings.fetchNextPage()}
                    label="Load more findings"
                  />
                )}
              </section>
              <section id="recommendations" aria-labelledby="recommendations-title">
                <div className="section-heading">
                  <div>
                    <p className="eyebrow">Action layer</p>
                    <h2 id="recommendations-title">Recommendations</h2>
                  </div>
                  <span>{data.recommendation_count}</span>
                </div>
                {!canWrite && (
                  <p className="permission-note section-permission" id="recommendations-readonly">
                    Viewer access · recommendation statuses are read only.
                  </p>
                )}
                {recommendationRows.map((item, index) => (
                  <RecommendationCard
                    auditId={id}
                    item={item}
                    index={index}
                    canWrite={canWrite}
                    evidenceHref={
                      item.related_finding_id
                        ? `#finding-${item.related_finding_id}`
                        : auditEvidenceAnchor(item.evidence_kind)
                    }
                    key={item.id}
                  />
                ))}
                {recommendationRows.length === 0 && !recommendations.error && (
                  <div className="section-empty">
                    <p>
                      {isCompleted && !isFinalizing
                        ? "No recommendations were generated."
                        : "Recommendations will appear when final analysis is ready."}
                    </p>
                  </div>
                )}
                {recommendations.hasNextPage && (
                  <LoadMoreButton
                    fullWidth
                    isLoading={recommendations.isFetchingNextPage}
                    onLoad={() => void recommendations.fetchNextPage()}
                    label="Load more recommendations"
                  />
                )}
              </section>
            </div>

            <div className="evidence">
              <section id="page-evidence" aria-labelledby="page-evidence-title">
                <div className="section-heading">
                  <h2 id="page-evidence-title">Page evidence</h2>
                  <span>{data.page_count}</span>
                </div>
                {pageRows.map((page) => (
                  <div className="evidence-row" key={page.id}>
                    <span className="http">{page.status_code}</span>
                    <div>
                      <strong>{page.title}</strong>
                      <p>
                        <EvidenceUrl url={page.url} />
                      </p>
                    </div>
                  </div>
                ))}
                {pageRows.length === 0 && !pages.error && (
                  <div className="section-empty">
                    <p>
                      {isCompleted && !isFinalizing
                        ? "No page evidence was recorded."
                        : "Page evidence will appear during analysis."}
                    </p>
                  </div>
                )}
                {pages.hasNextPage && (
                  <LoadMoreButton
                    fullWidth
                    isLoading={pages.isFetchingNextPage}
                    onLoad={() => void pages.fetchNextPage()}
                    label="Load more pages"
                  />
                )}
              </section>
              <section id="prompt-evidence" aria-labelledby="prompt-evidence-title">
                <div className="section-heading">
                  <h2 id="prompt-evidence-title">Prompt evidence</h2>
                  <span>{data.prompt_count}</span>
                </div>
                {promptRows.map((prompt) => (
                  <div className="evidence-row prompt-evidence-row" key={prompt.id}>
                    <span
                      className={prompt.mentioned_brand ? "signal yes" : "signal no"}
                      aria-label={prompt.mentioned_brand ? "Brand mentioned" : "Brand absent"}
                    >
                      {prompt.mentioned_brand ? "✓" : "×"}
                    </span>
                    <div>
                      <strong>{prompt.prompt}</strong>
                      <p>
                        {prompt.mentioned_brand ? "Brand mentioned" : "Brand absent"} ·{" "}
                        {prompt.source.replaceAll("_", " ")}
                      </p>
                      <div className="competitor-mentions">
                        <span>
                          {prompt.competitors_mentioned.length
                            ? "Competitors surfaced"
                            : "No tracked competitors surfaced"}
                        </span>
                        {prompt.competitors_mentioned.map((competitor) => (
                          <em key={competitor}>{competitor}</em>
                        ))}
                      </div>
                    </div>
                  </div>
                ))}
                {promptRows.length === 0 && !prompts.error && (
                  <div className="section-empty">
                    <p>
                      {isCompleted && !isFinalizing
                        ? "No prompt evidence was recorded."
                        : "Prompt evidence will appear during analysis."}
                    </p>
                  </div>
                )}
                {prompts.hasNextPage && (
                  <LoadMoreButton
                    fullWidth
                    isLoading={prompts.isFetchingNextPage}
                    onLoad={() => void prompts.fetchNextPage()}
                    label="Load more prompts"
                  />
                )}
              </section>
            </div>
            <section className="timeline" id="audit-timeline" aria-label="Audit timeline">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">System record</p>
                  <h2>Audit timeline</h2>
                </div>
                <span>{data.event_count}</span>
              </div>
              {eventRows.map((event) => (
                <div className="timeline-row" key={event.id}>
                  <span aria-hidden="true" />
                  <div>
                    <strong>{event.message}</strong>
                    <p>
                      <time dateTime={event.created_at}>
                        {new Date(event.created_at).toLocaleTimeString()}
                      </time>{" "}
                      · {event.event_type.replaceAll("_", " ")}
                    </p>
                  </div>
                </div>
              ))}
              {eventRows.length === 0 && !events.error && (
                <div className="section-empty">
                  <p>Lifecycle events will appear here.</p>
                </div>
              )}
              {events.hasNextPage && (
                <LoadMoreButton
                  fullWidth
                  isLoading={events.isFetchingNextPage}
                  onLoad={() => void events.fetchNextPage()}
                  label="Load more events"
                />
              )}
            </section>
          </>
        )}
      </section>
    </Shell>
  );
}
