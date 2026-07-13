// @vitest-environment jsdom

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CreateProjectDialog } from "./create-project-dialog";

describe("CreateProjectDialog", () => {
  it("announces validation errors and focuses the first invalid field", () => {
    const submit = vi.fn();
    render(<CreateProjectDialog open onOpenChange={vi.fn()} onSubmit={submit} isPending={false} />);

    fireEvent.click(screen.getByRole("button", { name: "Create project" }));

    expect(submit).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(screen.getByLabelText("Project name"));
    expect(screen.getAllByRole("alert").map((alert) => alert.textContent)).toEqual([
      "Enter a project name.",
      "Enter a valid domain such as example.com.",
    ]);
  });
});
