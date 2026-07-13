"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { FindingCard } from "@/components/finding-card";
import { LoadMoreButton } from "@/components/load-more-button";
import { ErrorBox, Shell } from "@/components/shell";
import { FindingsSkeleton } from "@/components/skeletons";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { usePageTitle } from "@/lib/use-page-title";

const categories = [
  "ai_visibility",
  "technical_seo",
  "content_gap",
  "competitor_mention",
  "citation_gap",
];

function FindingsContent() {
  const search = useSearchParams();
  const router = useRouter();
  const [projectSearch, setProjectSearch] = useState("");
  const [debouncedProjectSearch, setDebouncedProjectSearch] = useState("");
  const severity = search.get("severity") ?? "";
  const category = search.get("category") ?? "";
  const projectId = search.get("project_id") ?? "";
  const auditId = search.get("audit_id") ?? "";
  const filters = { severity, category, project_id: projectId, audit_id: auditId };

  usePageTitle("Findings");

  useEffect(() => {
    const timeout = globalThis.setTimeout(
      () => setDebouncedProjectSearch(projectSearch.trim()),
      300,
    );
    return () => globalThis.clearTimeout(timeout);
  }, [projectSearch]);

  const projectOptions = useInfiniteQuery({
    queryKey: queryKeys.projectOptions(debouncedProjectSearch),
    queryFn: ({ pageParam, signal }) => api.projects(pageParam, 20, debouncedProjectSearch, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  });
  const selectedProject = useQuery({
    queryKey: queryKeys.project(projectId),
    queryFn: ({ signal }) => api.project(projectId, signal),
    enabled: !!projectId,
  });
  const auditOptions = useInfiniteQuery({
    queryKey: queryKeys.auditOptions(projectId),
    queryFn: ({ pageParam, signal }) => api.audits(projectId, pageParam, 20, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    enabled: !!projectId,
  });
  const findings = useInfiniteQuery({
    queryKey: queryKeys.findings(filters),
    queryFn: ({ pageParam, signal }) => api.findings({ ...filters, cursor: pageParam }, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  });
  const projects = projectOptions.data?.pages.flatMap((page) => page.items) ?? [];
  const audits = auditOptions.data?.pages.flatMap((page) => page.items) ?? [];
  const rows = findings.data?.pages.flatMap((page) => page.items) ?? [];
  const selectedProjectIsMissing =
    !!projectId && !projects.some((project) => project.id === projectId);
  const selectedAuditIsMissing = !!auditId && !audits.some((audit) => audit.id === auditId);
  const activeFilterCount = [severity, category, projectId, auditId].filter(Boolean).length;

  function updateFilter(name: "severity" | "category" | "project_id" | "audit_id", value: string) {
    const params = new URLSearchParams(search.toString());
    if (value) params.set(name, value);
    else params.delete(name);
    const query = params.toString();
    router.replace(query ? `/findings?${query}` : "/findings", { scroll: false });
  }

  function changeProject(nextProjectId: string) {
    const params = new URLSearchParams(search.toString());
    if (nextProjectId) params.set("project_id", nextProjectId);
    else params.delete("project_id");
    params.delete("audit_id");
    const query = params.toString();
    router.replace(query ? `/findings?${query}` : "/findings", { scroll: false });
  }

  function clearFilters() {
    setProjectSearch("");
    router.replace("/findings", { scroll: false });
  }

  return (
    <Shell>
      <header className="topbar">
        <div>
          <p className="eyebrow">Search and filtering</p>
          <h1>Findings</h1>
          <p>Explore tenant-scoped visibility issues without memorizing internal IDs.</p>
        </div>
      </header>
      <section className="content">
        <form
          className="filters"
          aria-label="Finding filters"
          onSubmit={(event) => event.preventDefault()}
        >
          <fieldset>
            <legend className="sr-only">Filter visibility findings</legend>
            <label htmlFor="finding-severity">
              Severity
              <select
                id="finding-severity"
                value={severity}
                onChange={(event) => updateFilter("severity", event.target.value)}
              >
                <option value="">All severities</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </label>
            <label htmlFor="finding-category">
              Category
              <select
                id="finding-category"
                value={category}
                onChange={(event) => updateFilter("category", event.target.value)}
              >
                <option value="">All categories</option>
                {categories.map((value) => (
                  <option key={value} value={value}>
                    {value.replaceAll("_", " ")}
                  </option>
                ))}
              </select>
            </label>
            <div className="filter-field">
              <label htmlFor="finding-project-search">Project</label>
              <input
                id="finding-project-search"
                type="search"
                value={projectSearch}
                onChange={(event) => setProjectSearch(event.target.value)}
                placeholder="Search name or domain"
                autoComplete="off"
              />
              <label className="sr-only" htmlFor="finding-project">
                Choose a project
              </label>
              <select
                id="finding-project"
                value={projectId}
                onChange={(event) => changeProject(event.target.value)}
                disabled={projectOptions.isLoading}
              >
                <option value="">All projects</option>
                {selectedProjectIsMissing && (
                  <option value={projectId}>
                    {selectedProject.data
                      ? `${selectedProject.data.name} · ${selectedProject.data.domain}`
                      : "Selected project"}
                  </option>
                )}
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name} · {project.domain}
                  </option>
                ))}
              </select>
              {projectOptions.hasNextPage && (
                <LoadMoreButton
                  isLoading={projectOptions.isFetchingNextPage}
                  onLoad={() => void projectOptions.fetchNextPage()}
                  label="Load more projects"
                />
              )}
            </div>
            <div className="filter-field">
              <label htmlFor="finding-audit">Audit</label>
              <select
                id="finding-audit"
                value={auditId}
                onChange={(event) => updateFilter("audit_id", event.target.value)}
                disabled={!projectId || auditOptions.isLoading}
              >
                <option value="">
                  {projectId ? "All project audits" : "Select a project first"}
                </option>
                {selectedAuditIsMissing && (
                  <option value={auditId}>Selected audit #{auditId.slice(-8)}</option>
                )}
                {audits.map((audit) => (
                  <option key={audit.id} value={audit.id}>
                    #{audit.id.slice(-8)} · {audit.status} ·{" "}
                    {new Date(audit.created_at).toLocaleString()}
                  </option>
                ))}
              </select>
              {auditOptions.hasNextPage && (
                <LoadMoreButton
                  isLoading={auditOptions.isFetchingNextPage}
                  onLoad={() => void auditOptions.fetchNextPage()}
                  label="Load more audits"
                />
              )}
            </div>
            <div className="filter-actions">
              <span className="filter-summary" aria-live="polite">
                {activeFilterCount
                  ? `${activeFilterCount} active ${activeFilterCount === 1 ? "filter" : "filters"}`
                  : "Showing all findings"}
              </span>
              <button
                className="secondary"
                type="button"
                onClick={clearFilters}
                disabled={activeFilterCount === 0 && !projectSearch}
              >
                Clear filters
              </button>
            </div>
          </fieldset>
        </form>
        {projectOptions.error && (
          <ErrorBox
            message={`Project filter options could not be loaded. ${projectOptions.error.message}`}
            error={projectOptions.error}
            onRetry={() => void projectOptions.refetch()}
          />
        )}
        {auditOptions.error && (
          <ErrorBox
            message={`Audit filter options could not be loaded. ${auditOptions.error.message}`}
            error={auditOptions.error}
            onRetry={() => void auditOptions.refetch()}
          />
        )}
        {findings.isLoading && <FindingsSkeleton />}
        {findings.error && (
          <ErrorBox error={findings.error} onRetry={() => void findings.refetch()} />
        )}
        {!findings.isLoading && !findings.error && rows.length === 0 && (
          <div className="empty compact">
            <h2>No matching findings</h2>
            <p>
              {activeFilterCount
                ? "Try a broader combination of filters."
                : "Complete an audit to generate your first findings."}
            </p>
            {activeFilterCount > 0 && (
              <button className="secondary" onClick={clearFilters}>
                Clear filters
              </button>
            )}
          </div>
        )}
        {rows.length > 0 && (
          <>
            <div className="results-meta">
              <strong>
                {rows.length}
                {findings.hasNextPage ? "+" : ""}
              </strong>{" "}
              findings shown
            </div>
            <div className="finding-list">
              {rows.map((item) => (
                <FindingCard item={item} showContext key={item.id} />
              ))}
            </div>
          </>
        )}
        {findings.hasNextPage && (
          <div className="load-more">
            <LoadMoreButton
              isLoading={findings.isFetchingNextPage}
              onLoad={() => void findings.fetchNextPage()}
              label="Load more findings"
            />
          </div>
        )}
      </section>
    </Shell>
  );
}

export default function FindingsPage() {
  return (
    <Suspense
      fallback={
        <div className="session-loading" role="status">
          Loading findings…
        </div>
      }
    >
      <FindingsContent />
    </Suspense>
  );
}
