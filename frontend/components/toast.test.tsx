// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider, useToast } from "./toast";

function ToastControls() {
  const { showToast } = useToast();
  return (
    <>
      <button onClick={() => showToast({ title: "Saved", tone: "success" })}>Success</button>
      <button
        onClick={() =>
          showToast({ title: "Failed", description: "Try again later", tone: "error" })
        }
      >
        Error
      </button>
      <button onClick={() => showToast({ title: "Information" })}>Information</button>
    </>
  );
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("ToastProvider", () => {
  it("announces, bounds, and manually dismisses notifications", () => {
    render(
      <ToastProvider>
        <ToastControls />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Success" }));
    fireEvent.click(screen.getByRole("button", { name: "Information" }));
    fireEvent.click(screen.getByRole("button", { name: "Success" }));
    fireEvent.click(screen.getByRole("button", { name: "Information" }));

    expect(screen.getAllByRole("status")).toHaveLength(3);
    expect(screen.getAllByText("Saved")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Dismiss Saved" }));
    expect(screen.queryByText("Saved")).toBeNull();
  });

  it("uses alert semantics and the longer error timeout", () => {
    vi.useFakeTimers();
    render(
      <ToastProvider>
        <ToastControls />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Error" }));
    expect(screen.getByRole("alert").textContent).toContain("Try again later");

    act(() => vi.advanceTimersByTime(4_500));
    expect(screen.getByRole("alert")).toBeTruthy();
    act(() => vi.advanceTimersByTime(2_000));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("fails clearly when the hook is used outside its provider", () => {
    expect(() => render(<ToastControls />)).toThrow("useToast must be used within ToastProvider");
  });
});
