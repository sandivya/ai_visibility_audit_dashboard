"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { FindingsIcon, ProjectsIcon } from "@/components/icons";
import { useToast } from "@/components/toast";
import { api, ApiError } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";

export function Shell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const session = useQuery({
    queryKey: queryKeys.session,
    queryFn: ({ signal }) => api.me(signal),
    retry: false,
  });
  const config = useQuery({
    queryKey: queryKeys.authConfig,
    queryFn: ({ signal }) => api.authConfig(signal),
  });
  const { data: users = [] } = useQuery({
    queryKey: queryKeys.loginUsers,
    queryFn: ({ signal }) => api.loginUsers(signal),
    enabled: config.data?.mock_auth_enabled === true,
  });
  const switchUser = useMutation({
    mutationFn: api.login,
    onSuccess: (user) => {
      queryClient.clear();
      queryClient.setQueryData(queryKeys.session, user);
      showToast({
        title: "Workspace switched",
        description: `You’re now viewing ${user.organization_name}.`,
        tone: "success",
      });
      router.push("/");
    },
  });
  const logout = useMutation({
    mutationFn: api.logout,
    onSuccess: () => {
      queryClient.clear();
      router.push("/login");
    },
  });
  useEffect(() => {
    if (session.error) router.replace("/login");
  }, [router, session.error]);

  if (session.isLoading || session.error || !session.data) {
    return (
      <div className="session-loading" role="status" aria-live="polite">
        <div className="session-loading-inner">
          <span className="loading-mark" aria-hidden="true">
            V
          </span>
          <span>Checking your secure session…</span>
        </div>
      </div>
    );
  }

  const projectsActive =
    pathname === "/" ||
    pathname === "/projects" ||
    pathname.startsWith("/projects/") ||
    pathname.startsWith("/audits/");
  const findingsActive = pathname === "/findings" || pathname.startsWith("/findings/");

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <aside className="sidebar">
        <Link href="/" className="brand" aria-label="AI Visibility projects">
          <span className="brand-mark" aria-hidden="true">
            V
          </span>
          <span>AI Visibility</span>
        </Link>
        <nav aria-label="Primary navigation">
          <Link
            href="/"
            className={`nav-link${projectsActive ? " nav-active" : ""}`}
            aria-current={projectsActive ? "page" : undefined}
          >
            <span className="nav-icon">
              <ProjectsIcon />
            </span>
            <span>Projects</span>
          </Link>
          <Link
            href="/findings"
            className={`nav-link${findingsActive ? " nav-active" : ""}`}
            aria-current={findingsActive ? "page" : undefined}
          >
            <span className="nav-icon">
              <FindingsIcon />
            </span>
            <span>Findings</span>
          </Link>
        </nav>
        <div className="tenant">
          <label htmlFor="user">Viewing workspace</label>
          {config.data?.mock_auth_enabled ? (
            <select
              id="user"
              value={session.data.id}
              disabled={switchUser.isPending}
              onChange={(event) => switchUser.mutate(event.target.value)}
            >
              {users.map((user) => (
                <option value={user.id} key={user.id}>
                  {user.organization_name} · {user.email}
                </option>
              ))}
            </select>
          ) : (
            <div className="workspace-identity">
              <strong>{session.data.organization_name}</strong>
              <span>
                {session.data.email} · {session.data.role}
              </span>
            </div>
          )}
          <p>Revocable HttpOnly session · backend scoped</p>
          {switchUser.error ? (
            <p className="sidebar-error" role="alert">
              Couldn’t switch workspace. Try again.
            </p>
          ) : null}
          {logout.error ? (
            <p className="sidebar-error" role="alert">
              Couldn’t sign out. Try again.
            </p>
          ) : null}
          <button className="logout" onClick={() => logout.mutate()} disabled={logout.isPending}>
            {logout.isPending ? "Signing out…" : "Sign out"}
          </button>
        </div>
      </aside>
      <main id="main-content" tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}

export function Status({ value }: { value: string }) {
  const label = value.replaceAll("_", " ");
  return (
    <span className={`status ${value}`} aria-label={`Status: ${label}`}>
      {label}
    </span>
  );
}
export function Score({ value }: { value: number | null }) {
  return value === null ? (
    <span className="muted" aria-label="Score unavailable">
      —
    </span>
  ) : (
    <div className="score" aria-label={`Score: ${value} out of 100`}>
      <strong>{value}</strong>
      <span aria-hidden="true">/100</span>
    </div>
  );
}

type ErrorBoxProps = {
  message?: string;
  error?: Error | null;
  onRetry?: () => void;
  retryLabel?: string;
};

export function ErrorBox({ message, error, onRetry, retryLabel = "Try again" }: ErrorBoxProps) {
  const [referenceCopied, setReferenceCopied] = useState(false);
  const apiError = error instanceof ApiError ? error : null;
  const detail = message ?? error?.message ?? "The request could not be completed.";

  async function copyReference() {
    if (!apiError?.requestId) return;
    try {
      await navigator.clipboard.writeText(apiError.requestId);
      setReferenceCopied(true);
      globalThis.setTimeout(() => setReferenceCopied(false), 2_000);
    } catch {
      setReferenceCopied(false);
    }
  }

  return (
    <div className="error-box" role="alert">
      <strong>Something needs attention</strong>
      <p>{detail}</p>
      {apiError?.retryAfter && (
        <p className="error-guidance">
          The server asked clients to retry after {apiError.retryAfter}.
        </p>
      )}
      {(apiError || onRetry) && (
        <div className="error-actions">
          {apiError && (
            <div className="error-reference">
              <span>
                {apiError.requestId ? "Support reference" : "Error code"} · {apiError.code}
              </span>
              {apiError.requestId && (
                <>
                  <code>{apiError.requestId}</code>
                  <button type="button" className="error-copy" onClick={() => void copyReference()}>
                    {referenceCopied ? "Copied" : "Copy reference"}
                  </button>
                  <span className="sr-only" aria-live="polite">
                    {referenceCopied ? "Support reference copied" : ""}
                  </span>
                </>
              )}
            </div>
          )}
          {onRetry && (
            <button type="button" className="secondary" onClick={onRetry}>
              {retryLabel}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
