// @vitest-environment jsdom

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LoadMoreButton } from "./load-more-button";

describe("LoadMoreButton", () => {
  it("invokes loading and exposes its busy state", () => {
    const onLoad = vi.fn();
    const { rerender } = render(
      <LoadMoreButton isLoading={false} onLoad={onLoad} label="Load more findings" />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Load more findings" }));
    expect(onLoad).toHaveBeenCalledOnce();

    rerender(<LoadMoreButton isLoading onLoad={onLoad} label="Load more findings" fullWidth />);
    const loading = screen.getByRole("button", { name: "Loading more…" });
    expect(loading.hasAttribute("disabled")).toBe(true);
    expect(loading.getAttribute("aria-busy")).toBe("true");
    expect(loading.className).toContain("evidence-more");
  });
});
