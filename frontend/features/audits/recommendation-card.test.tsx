// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/components/toast";
import { api } from "@/lib/api";
import type { Recommendation } from "@/lib/types";
import { RecommendationCard } from "./recommendation-card";

const recommendation: Recommendation = {
  id: "rec_test",
  audit_id: "aud_test",
  priority: "high",
  title: "Publish comparison-led content",
  description: "Create evidence-backed category comparisons.",
  status: "open",
  evidence_kind: "prompts",
  related_finding_id: "finding_test",
  related_finding_category: "ai_visibility",
  created_at: "2026-07-13T00:00:00Z",
  updated_at: "2026-07-13T00:00:00Z",
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
});

describe("RecommendationCard", () => {
  it("updates a writable recommendation and announces success", async () => {
    const update = vi
      .spyOn(api, "updateRecommendation")
      .mockResolvedValue({ ...recommendation, status: "completed" });
    render(
      <RecommendationCard
        auditId="aud_test"
        item={recommendation}
        index={0}
        canWrite
        evidenceHref="#findings"
      />,
      { wrapper: Providers },
    );

    fireEvent.change(screen.getByLabelText(`Status for ${recommendation.title}`), {
      target: { value: "completed" },
    });

    await waitFor(() => expect(update).toHaveBeenCalledWith("rec_test", "completed"));
    expect(await screen.findByText("Recommendation updated")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Review diagnostic evidence" }).getAttribute("href"),
    ).toBe("#findings");
  });

  it("shows mutation errors and disables read-only controls", async () => {
    vi.spyOn(api, "updateRecommendation").mockRejectedValue(new Error("Save failed"));
    const { rerender } = render(
      <RecommendationCard auditId="aud_test" item={recommendation} index={1} canWrite />,
      { wrapper: Providers },
    );

    fireEvent.change(screen.getByLabelText(`Status for ${recommendation.title}`), {
      target: { value: "dismissed" },
    });
    expect((await screen.findByRole("alert")).textContent).toContain("Update failed");

    rerender(
      <RecommendationCard auditId="aud_test" item={recommendation} index={1} canWrite={false} />,
    );
    expect(
      screen.getByLabelText(`Status for ${recommendation.title}`).hasAttribute("disabled"),
    ).toBe(true);
    expect(screen.getByText("02")).toBeTruthy();
  });
});
