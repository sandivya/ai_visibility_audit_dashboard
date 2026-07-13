"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { LoadMoreButton } from "@/components/load-more-button";
import { ErrorBox, Score, Shell, Status } from "@/components/shell";
import { ProjectsSkeleton } from "@/components/skeletons";
import { useToast } from "@/components/toast";
import { CreateProjectDialog, type ProjectDraft } from "@/features/projects/create-project-dialog";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { usePageTitle } from "@/lib/use-page-title";

export default function ProjectsPage() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const createButtonRef = useRef<HTMLButtonElement>(null);
  const router = useRouter();
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  usePageTitle("Projects");
  const session = useQuery({
    queryKey: queryKeys.session,
    queryFn: ({ signal }) => api.me(signal),
    retry: false,
  });
  const canWrite = session.data?.role !== "viewer";
  const query = useInfiniteQuery({
    queryKey: queryKeys.projects,
    queryFn: ({ pageParam, signal }) => api.projects(pageParam, 20, undefined, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  });
  const projects = query.data?.pages.flatMap((page) => page.items) ?? [];
  const create = useMutation({
    mutationFn: api.createProject,
    onSuccess: (project) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects });
      setDialogOpen(false);
      showToast({
        title: "Project created",
        description: "Your visibility workspace is ready for its first audit.",
        tone: "success",
      });
      router.push(`/projects/${project.id}`);
    },
  });

  function createProject(draft: ProjectDraft) {
    create.mutate(draft);
  }

  function openCreateDialog() {
    create.reset();
    setDialogOpen(true);
  }

  const completedLatestAudits = projects.filter(
    (project) => project.latest_audit?.status === "completed",
  ).length;

  return (
    <Shell>
      <header className="topbar">
        <div>
          <p className="eyebrow">Visibility operations</p>
          <h1>Projects</h1>
          <p>Monitor how brands appear across AI answers and search.</p>
        </div>
        <div className="topbar-actions">
          <button
            ref={createButtonRef}
            onClick={openCreateDialog}
            disabled={!canWrite}
            aria-haspopup="dialog"
            aria-expanded={dialogOpen}
          >
            + New project
          </button>
          {!canWrite && (
            <span className="permission-note">Viewer access · creation is read only</span>
          )}
        </div>
      </header>
      <section className="content">
        {query.isLoading && <ProjectsSkeleton />}
        {query.error && (
          <ErrorBox
            message={
              query.data ? `Projects could not be refreshed. ${query.error.message}` : undefined
            }
            error={query.error}
            onRetry={() => void query.refetch()}
          />
        )}
        {query.data && (
          <>
            <div className="metric-strip">
              <div>
                <span>Projects loaded</span>
                <strong>{projects.length}</strong>
              </div>
              <div>
                <span>Latest audits complete</span>
                <strong>{completedLatestAudits}</strong>
              </div>
              <div>
                <span>Your workspace role</span>
                <strong className="capitalize">{session.data?.role ?? "—"}</strong>
              </div>
            </div>
            {projects.length === 0 ? (
              <div className="empty">
                <span aria-hidden="true">◎</span>
                <h2>
                  {canWrite
                    ? "Create your first visibility project"
                    : "No projects are available yet"}
                </h2>
                <p>
                  {canWrite
                    ? "Add a brand and competitors to generate an evidence-backed audit."
                    : "Ask a workspace owner to create a project for your team."}
                </p>
                {canWrite && (
                  <button
                    onClick={openCreateDialog}
                    aria-haspopup="dialog"
                    aria-expanded={dialogOpen}
                  >
                    Create project
                  </button>
                )}
              </div>
            ) : (
              <div className="project-grid">
                {projects.map((project) => (
                  <Link className="project-card" href={`/projects/${project.id}`} key={project.id}>
                    <div className="card-head">
                      <div className="domain-mark" aria-hidden="true">
                        {project.name.slice(0, 2).toUpperCase()}
                      </div>
                      {project.latest_audit ? (
                        <Status value={project.latest_audit.status} />
                      ) : (
                        <span className="status never">not audited</span>
                      )}
                    </div>
                    <h2>{project.name}</h2>
                    <p className="domain">{project.domain}</p>
                    <p className="created">
                      Created {new Date(project.created_at).toLocaleString()}
                    </p>
                    <div
                      className="competitors"
                      aria-label={`${project.competitors.length} competitors`}
                    >
                      {project.competitors.length === 0 && <span>No competitors</span>}
                      {project.competitors.slice(0, 2).map((item) => (
                        <span key={item}>{item}</span>
                      ))}
                      {project.competitors.length > 2 && (
                        <span>+{project.competitors.length - 2}</span>
                      )}
                    </div>
                    <footer>
                      <div>
                        <small>Latest score</small>
                        <Score value={project.latest_audit?.visibility_score ?? null} />
                      </div>
                      <span className="arrow" aria-hidden="true">
                        →
                      </span>
                    </footer>
                  </Link>
                ))}
              </div>
            )}
            {query.hasNextPage && (
              <div className="load-more">
                <LoadMoreButton
                  isLoading={query.isFetchingNextPage}
                  onLoad={() => void query.fetchNextPage()}
                  label="Load more projects"
                />
              </div>
            )}
          </>
        )}
      </section>
      <CreateProjectDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onSubmit={createProject}
        isPending={create.isPending}
        error={create.error}
        returnFocusRef={createButtonRef}
      />
    </Shell>
  );
}
