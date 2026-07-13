"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { ErrorBox } from "@/components/shell";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { usePageTitle } from "@/lib/use-page-title";

export default function LoginPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  usePageTitle("Sign in");
  const config = useQuery({
    queryKey: queryKeys.authConfig,
    queryFn: ({ signal }) => api.authConfig(signal),
  });
  const users = useQuery({
    queryKey: queryKeys.loginUsers,
    queryFn: ({ signal }) => api.loginUsers(signal),
    enabled: config.data?.mock_auth_enabled === true,
  });
  const login = useMutation({
    mutationFn: api.login,
    onSuccess: (user) => {
      queryClient.clear();
      queryClient.setQueryData(queryKeys.session, user);
      router.replace("/");
    },
  });
  const loading = config.isLoading || (config.data?.mock_auth_enabled && users.isLoading);

  return (
    <main className="login-page">
      <section className="login-card" aria-labelledby="login-title">
        <div className="brand login-brand">
          <span className="brand-mark" aria-hidden="true">
            V
          </span>
          <span>
            Visibility<span>Stack</span>
          </span>
        </div>
        <p className="eyebrow">Secure demo access</p>
        <h1 id="login-title">Choose a test workspace</h1>
        <p>
          Review tenant isolation and role-aware workflows using one of the prepared enterprise
          workspaces.
        </p>
        {loading && (
          <div className="login-skeleton skeleton-region" role="status" aria-busy="true">
            <span className="sr-only">Loading sign-in options</span>
            <span className="skeleton-line medium" aria-hidden="true" />
            <span className="skeleton-block" aria-hidden="true" />
            <span className="skeleton-block" aria-hidden="true" />
          </div>
        )}
        {config.error && <ErrorBox error={config.error} onRetry={() => void config.refetch()} />}
        {users.error && <ErrorBox error={users.error} onRetry={() => void users.refetch()} />}
        {config.data?.oidc_enabled && (
          <a className="oidc-login" href={api.oidcLoginUrl()}>
            Continue with enterprise SSO
          </a>
        )}
        {config.data?.mock_auth_enabled && !users.isLoading && (
          <div className="login-users" aria-label="Test workspaces">
            {users.data?.map((user) => (
              <button
                key={user.id}
                onClick={() => login.mutate(user.id)}
                disabled={login.isPending}
              >
                <strong>{user.organization_name}</strong>
                <span>
                  {user.email} · {user.role}
                </span>
              </button>
            ))}
          </div>
        )}
        {config.data && !config.data.oidc_enabled && !config.data.mock_auth_enabled && (
          <ErrorBox message="No authentication method is configured." />
        )}
        {login.error && (
          <ErrorBox error={login.error} onRetry={() => login.reset()} retryLabel="Dismiss" />
        )}
        {login.isPending && (
          <p className="login-status" role="status">
            Opening the selected workspace…
          </p>
        )}
      </section>
    </main>
  );
}
