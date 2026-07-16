"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { FindingCard } from "@/components/finding-card";
import { LoadMoreButton } from "@/components/load-more-button";
import { ErrorBox, Score, Shell, Status } from "@/components/shell";
import { AuditHistorySkeleton, ProjectDetailSkeleton } from "@/components/skeletons";
import { useToast } from "@/components/toast";
import { useAuditStatus, useStartAudit } from "@/features/audits/hooks";
import { auditEvidenceAnchor } from "@/features/audits/view-model";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { usePageTitle } from "@/lib/use-page-title";

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { showToast } = useToast();
  const session = useQuery({
    queryKey: queryKeys.session,
    queryFn: ({ signal }) => api.me(signal),
    retry: false,
  });
  const canWrite = session.data?.role !== "viewer";
  const project = useQuery({
    queryKey: queryKeys.project(id),
    queryFn: ({ signal }) => api.project(id, signal),
  });
  const latestId = project.data?.latest_audit?.id ?? "";
  const liveLatest = useAuditStatus(latestId, project.data?.latest_audit ?? undefined);
  const audits = useInfiniteQuery({
    queryKey: queryKeys.projectAudits(id),
    queryFn: ({ pageParam, signal }) => api.audits(id, pageParam, 20, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    enabled: !!project.data,
  });
  const latest = useQuery({
    queryKey: queryKeys.audit(latestId || "latest"),
    queryFn: ({ signal }) => api.audit(latestId, signal),
    enabled: !!latestId,
  });
  const start = useStartAudit(id, {
    onSuccess: (audit) => {
      showToast({
        title: "Audit queued",
        description: "We’ll update the results automatically as analysis completes.",
        tone: "success",
      });
      router.push(`/audits/${audit.id}`);
    },
  });

  usePageTitle(project.data?.name ?? "Project");

  const auditRows =
    audits.data?.pages
      .flatMap((page) => page.items)
      .map((audit) =>
        liveLatest.data?.id === audit.id ? { ...audit, ...liveLatest.data } : audit,
      ) ?? [];
  const completedScores = auditRows.flatMap((audit) =>
    audit.status === "completed" && audit.visibility_score !== null ? [audit.visibility_score] : [],
  );
  const scoreDelta = completedScores.length >= 2 ? completedScores[0] - completedScores[1] : null;
  const latestSummary =
    project.data?.latest_audit && liveLatest.data?.id === project.data.latest_audit.id
      ? { ...project.data.latest_audit, ...liveLatest.data }
      : project.data?.latest_audit;

  function startAudit() {
    if (canWrite && project.data) start.mutate();
  }

  return (
    <Shell>
      <header className="topbar">
        <div>
          <Link href="/" className="back">
            ← All projects
          </Link>
          <h1>{project.data?.name ?? "Project"}</h1>
          <p>{project.data?.domain ?? "Visibility workspace"}</p>
        </div>
        <div className="topbar-actions">
          <button onClick={startAudit} disabled={!canWrite || start.isPending || !project.data}>
            {start.isPending ? "Starting audit…" : "Run new audit"}
          </button>
          {!canWrite && (
            <span className="permission-note">Viewer access · audits are read only</span>
          )}
        </div>
      </header>
      <section className="content">
        {project.isLoading && <ProjectDetailSkeleton />}
        {project.error && <ErrorBox error={project.error} onRetry={() => void project.refetch()} />}
        {start.error && (
          <ErrorBox error={start.error} onRetry={startAudit} retryLabel="Try starting again" />
        )}
        {liveLatest.error && project.data && (
          <ErrorBox
            message={`Live audit status could not be refreshed. ${liveLatest.error.message}`}
            error={liveLatest.error}
            onRetry={() => void liveLatest.refetch()}
          />
        )}
        {project.data && (
          <>
            <div className="project-hero">
              <div>
                <p className="eyebrow">Latest visibility</p>
                <Score value={latestSummary?.visibility_score ?? null} />
              </div>
              <div>
                <span>Latest status</span>
                {latestSummary ? (
                  <Status value={latestSummary.status} />
                ) : (
                  <span className="muted">No audits</span>
                )}
              </div>
              <div>
                <span>Score change</span>
                <strong
                  className={`score-trend ${
                    scoreDelta === null
                      ? "muted"
                      : scoreDelta > 0
                        ? "positive"
                        : scoreDelta < 0
                          ? "negative"
                          : "neutral"
                  }`}
                >
                  {scoreDelta === null
                    ? "Need 2 audits"
                    : scoreDelta > 0
                      ? `+${scoreDelta}`
                      : scoreDelta === 0
                        ? "No change"
                        : scoreDelta}
                </strong>
                <small>
                  {scoreDelta === null ? "Run another completed audit" : "vs prior completed audit"}
                </small>
              </div>
              <div>
                <span>Created</span>
                <strong>{new Date(project.data.created_at).toLocaleString()}</strong>
              </div>
            </div>

            {latestSummary && (
              <aside
                className="methodology-panel methodology-panel-compact"
                aria-label="Audit methodology"
              >
                <div className="methodology-heading">
                  <div>
                    <p className="eyebrow">Methodology</p>
                    <h2>Simulated demo data</h2>
                  </div>
                  <span>{latestSummary.methodology.version}</span>
                </div>
                <p>{latestSummary.methodology.disclosure}</p>
              </aside>
            )}

            <section className="competitor-panel" aria-labelledby="tracked-competitors-title">
              <div>
                <p className="eyebrow">Comparison set</p>
                <h2 id="tracked-competitors-title">Tracked competitors</h2>
                <p>
                  These brands are checked alongside {project.data.name} when prompt evidence is
                  analyzed.
                </p>
              </div>
              <div className="competitor-list">
                {project.data.competitors.length > 0 ? (
                  project.data.competitors.map((competitor) => (
                    <span key={competitor}>{competitor}</span>
                  ))
                ) : (
                  <span className="muted">No competitors configured</span>
                )}
              </div>
              {latestId && (
                <Link className="text-action" href={`/audits/${latestId}#prompt-evidence`}>
                  Review competitor mentions →
                </Link>
              )}
            </section>

            <div className="section-heading">
              <div>
                <p className="eyebrow">History</p>
                <h2>Audits</h2>
              </div>
            </div>
            {audits.isLoading && <AuditHistorySkeleton />}
            {audits.error && (
              <ErrorBox error={audits.error} onRetry={() => void audits.refetch()} />
            )}
            {!audits.isLoading && !audits.error && auditRows.length === 0 && (
              <div className="empty compact">
                <h2>No audit evidence yet</h2>
                <p>Run the first audit to generate pages, prompts, findings, and actions.</p>
                {canWrite && (
                  <button onClick={startAudit} disabled={start.isPending}>
                    {start.isPending ? "Starting audit…" : "Run first audit"}
                  </button>
                )}
              </div>
            )}
            {auditRows.length > 0 && (
              <div className="audit-table-wrap">
                <table className="audit-table">
                  <caption className="sr-only">Audit history for {project.data.name}</caption>
                  <thead>
                    <tr>
                      <th scope="col">Audit</th>
                      <th scope="col">Started</th>
                      <th scope="col">Status</th>
                      <th scope="col">Score</th>
                      <th scope="col">
                        <span className="sr-only">Open</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {auditRows.map((audit) => (
                      <tr key={audit.id}>
                        <td data-label="Audit">
                          <Link className="audit-id-link" href={`/audits/${audit.id}`}>
                            <span aria-hidden="true">#</span>
                            {audit.id.slice(-8)}
                          </Link>
                        </td>
                        <td data-label="Started">{new Date(audit.created_at).toLocaleString()}</td>
                        <td data-label="Status">
                          <Status value={audit.status} />
                        </td>
                        <td data-label="Score">
                          <Score value={audit.visibility_score} />
                        </td>
                        <td className="audit-open" data-label="Open">
                          <Link
                            href={`/audits/${audit.id}`}
                            aria-label={`Open audit ${audit.id.slice(-8)}`}
                          >
                            →
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {audits.hasNextPage && (
              <div className="load-more">
                <LoadMoreButton
                  isLoading={audits.isFetchingNextPage}
                  onLoad={() => void audits.fetchNextPage()}
                  label="Load more audits"
                />
              </div>
            )}
            {latestId && (
              <>
                <div className="section-heading latest-heading">
                  <div>
                    <p className="eyebrow">Latest output</p>
                    <h2>Findings and recommendations</h2>
                  </div>
                  {latest.data && <Link href={`/audits/${latest.data.id}`}>Open full audit →</Link>}
                </div>
                {latest.isLoading && <AuditHistorySkeleton />}
                {latest.error && (
                  <ErrorBox error={latest.error} onRetry={() => void latest.refetch()} />
                )}
                {latest.data && (
                  <div className="results-grid">
                    <section>
                      <h2>Latest findings</h2>
                      {latest.data.findings.length ? (
                        latest.data.findings.map((item) => (
                          <FindingCard
                            item={item}
                            evidenceHref={`/audits/${latest.data.id}${auditEvidenceAnchor(item.evidence_kind)}`}
                            key={item.id}
                          />
                        ))
                      ) : (
                        <div className="section-empty">
                          <p>
                            {latest.data.status === "completed"
                              ? "This audit completed without findings."
                              : "Findings will appear when analysis completes."}
                          </p>
                        </div>
                      )}
                    </section>
                    <section>
                      <h2>Latest recommendations</h2>
                      {latest.data.recommendations.length ? (
                        latest.data.recommendations.map((item) => (
                          <article className="result-card" key={item.id}>
                            <Status value={item.status} />
                            <h3>{item.title}</h3>
                            <p>{item.description}</p>
                            <Link
                              className="card-action"
                              href={`/audits/${latest.data.id}#recommendation-${item.id}`}
                            >
                              Open action workflow
                            </Link>
                          </article>
                        ))
                      ) : (
                        <div className="section-empty">
                          <p>
                            {latest.data.status === "completed"
                              ? "No recommendations were generated."
                              : "Recommendations will appear when analysis completes."}
                          </p>
                        </div>
                      )}
                    </section>
                  </div>
                )}
              </>
            )}
          </>
        )}
      </section>
    </Shell>
  );
}
