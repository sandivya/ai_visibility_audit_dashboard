// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CreateProjectDialog } from "./create-project-dialog";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

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

  it("submits a normalized valid project and closes safely", () => {
    const submit = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <CreateProjectDialog open onOpenChange={onOpenChange} onSubmit={submit} isPending={false} />,
    );

    fireEvent.change(screen.getByLabelText("Project name"), { target: { value: "  Acme  " } });
    fireEvent.change(screen.getByLabelText("Domain"), {
      target: { value: "https://acme.example/" },
    });
    fireEvent.change(screen.getByLabelText(/Competitors/), {
      target: { value: "rival.example, rival.example" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create project" }));

    expect(submit).toHaveBeenCalledWith({
      name: "Acme",
      domain: "acme.example",
      competitors: ["rival.example"],
    });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("ignores submission and dismissal while creation is pending", async () => {
    vi.stubGlobal("PointerEvent", MouseEvent);
    const submit = vi.fn();
    render(<CreateProjectDialog open onOpenChange={vi.fn()} onSubmit={submit} isPending />);

    fireEvent.submit(document.querySelector("form")!);
    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Creating project…" }).hasAttribute("disabled")).toBe(
      true,
    );
    fireEvent.keyDown(document, { key: "Escape" });
    await new Promise((resolve) => globalThis.setTimeout(resolve, 0));
    fireEvent.pointerDown(document.querySelector(".dialog-overlay")!, {
      button: 0,
      pointerType: "mouse",
    });
  });

  it("returns focus to the trigger after closing", async () => {
    function Harness() {
      const [open, setOpen] = useState(true);
      const trigger = useRef<HTMLButtonElement>(null);
      return (
        <>
          <button ref={trigger}>Open project dialog</button>
          <CreateProjectDialog
            open={open}
            onOpenChange={setOpen}
            onSubmit={vi.fn()}
            isPending={false}
            returnFocusRef={trigger}
          />
        </>
      );
    }
    render(<Harness />);

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("button", { name: "Open project dialog" }),
      ),
    );
  });
});
