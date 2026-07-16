// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";
import { ToastProvider } from "./toast";
import { Shell } from "./shell";

const navigation = vi.hoisted(() => ({
  pathname: "/findings",
  push: vi.fn(),
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
  useRouter: () => ({ push: navigation.push, replace: navigation.replace }),
}));

const alice: User = {
  id: "usr_alice",
  email: "alice@acme.com",
  org_id: "org_acme",
  organization_name: "Acme Skincare",
  role: "owner",
};
const bob: User = {
  id: "usr_bob",
  email: "bob@beta.com",
  org_id: "org_beta",
  organization_name: "Beta Finance",
  role: "owner",
};

function testClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

function Providers({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={testClient()}>
      <ToastProvider>{children}</ToastProvider>
    </QueryClientProvider>
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  navigation.push.mockReset();
  navigation.replace.mockReset();
  navigation.pathname = "/findings";
});

describe("Shell interactions", () => {
  it("switches workspaces, announces success, and signs out", async () => {
    vi.spyOn(api, "me").mockResolvedValue(alice);
    vi.spyOn(api, "authConfig").mockResolvedValue({
      mock_auth_enabled: true,
      oidc_enabled: false,
      oidc_login_url: null,
    });
    vi.spyOn(api, "loginUsers").mockResolvedValue([alice, bob]);
    const login = vi.spyOn(api, "login").mockResolvedValue(bob);
    const logout = vi.spyOn(api, "logout").mockResolvedValue(undefined);

    render(<Shell>Workspace content</Shell>, { wrapper: Providers });

    expect(await screen.findByText("Workspace content")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Findings" }).getAttribute("aria-current")).toBe(
      "page",
    );
    expect(await screen.findByRole("option", { name: /Beta Finance/ })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Viewing workspace"), {
      target: { value: "usr_bob" },
    });

    await waitFor(() => expect(login.mock.calls[0]?.[0]).toBe("usr_bob"));
    expect(await screen.findByText("Workspace switched")).toBeTruthy();
    expect(navigation.push).toHaveBeenCalledWith("/");

    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(logout).toHaveBeenCalledOnce());
    expect(navigation.push).toHaveBeenCalledWith("/login");
  });

  it("redirects failed sessions and renders a fixed workspace for production auth", async () => {
    vi.spyOn(api, "me").mockRejectedValueOnce(new Error("Unauthorized")).mockResolvedValue(alice);
    vi.spyOn(api, "authConfig").mockResolvedValue({
      mock_auth_enabled: false,
      oidc_enabled: true,
      oidc_login_url: "/api/auth/oidc/login",
    });

    const first = render(<Shell>Hidden content</Shell>, { wrapper: Providers });
    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/login"));
    expect(screen.getByText(/Checking your secure session/)).toBeTruthy();
    first.unmount();

    render(<Shell>Production content</Shell>, { wrapper: Providers });
    expect(await screen.findByText("Production content")).toBeTruthy();
    expect(screen.queryByLabelText("Viewing workspace")).toBeNull();
    expect(screen.getByText("alice@acme.com · owner")).toBeTruthy();
  });
});
