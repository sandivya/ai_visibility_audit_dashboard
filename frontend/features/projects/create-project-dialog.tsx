"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { FormEvent, useEffect, useState, type RefObject } from "react";
import { ErrorBox } from "@/components/shell";
import { validateProjectDraft, type ProjectDraft, type ProjectFormErrors } from "@/lib/validation";

export type { ProjectDraft } from "@/lib/validation";

type CreateProjectDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (draft: ProjectDraft) => void;
  isPending: boolean;
  error?: Error | null;
  returnFocusRef?: RefObject<HTMLButtonElement | null>;
};

export function CreateProjectDialog({
  open,
  onOpenChange,
  onSubmit,
  isPending,
  error,
  returnFocusRef,
}: CreateProjectDialogProps) {
  const [errors, setErrors] = useState<ProjectFormErrors>({});

  useEffect(() => {
    if (!open) setErrors({});
  }, [open]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isPending) return;
    const form = new FormData(event.currentTarget);
    const result = validateProjectDraft({
      name: String(form.get("name") ?? ""),
      domain: String(form.get("domain") ?? ""),
      competitors: String(form.get("competitors") ?? ""),
    });
    setErrors(result.errors);
    if (result.draft) {
      onSubmit(result.draft);
      return;
    }
    const firstInvalidField = Object.keys(result.errors)[0];
    const field = firstInvalidField
      ? event.currentTarget.elements.namedItem(firstInvalidField)
      : null;
    if (field instanceof HTMLElement) field.focus();
  }

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(nextOpen) => {
        if (!isPending) onOpenChange(nextOpen);
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content
          className="dialog-content"
          onCloseAutoFocus={(event) => {
            if (returnFocusRef?.current) {
              event.preventDefault();
              returnFocusRef.current.focus();
            }
          }}
          onEscapeKeyDown={(event) => {
            if (isPending) event.preventDefault();
          }}
          onPointerDownOutside={(event) => {
            if (isPending) event.preventDefault();
          }}
        >
          <div>
            <p className="eyebrow">New workspace</p>
            <Dialog.Title className="dialog-title">Create a project</Dialog.Title>
            <Dialog.Description className="dialog-description">
              Define the brand and competitor set you want to evaluate.
            </Dialog.Description>
          </div>
          <form className="dialog-form" onSubmit={submit} noValidate>
            <div className="form-field">
              <label htmlFor="project-name">Project name</label>
              <input
                id="project-name"
                name="name"
                required
                maxLength={120}
                placeholder="Acme Skincare"
                autoFocus
                aria-invalid={!!errors.name}
                aria-describedby={errors.name ? "project-name-error" : undefined}
              />
              {errors.name && (
                <span className="field-error" id="project-name-error" role="alert">
                  {errors.name}
                </span>
              )}
            </div>
            <div className="form-field">
              <label htmlFor="project-domain">Domain</label>
              <input
                id="project-domain"
                name="domain"
                required
                inputMode="url"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                placeholder="acmeskincare.com"
                aria-invalid={!!errors.domain}
                aria-describedby={
                  errors.domain ? "project-domain-hint project-domain-error" : "project-domain-hint"
                }
              />
              <span className="field-hint" id="project-domain-hint">
                Use the root domain without a path.
              </span>
              {errors.domain && (
                <span className="field-error" id="project-domain-error" role="alert">
                  {errors.domain}
                </span>
              )}
            </div>
            <div className="form-field">
              <label htmlFor="project-competitors">
                Competitors <span className="optional">Optional</span>
              </label>
              <input
                id="project-competitors"
                name="competitors"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                placeholder="glowco.com, naturalskin.com"
                aria-invalid={!!errors.competitors}
                aria-describedby={
                  errors.competitors
                    ? "project-competitors-hint project-competitors-error"
                    : "project-competitors-hint"
                }
              />
              <span className="field-hint" id="project-competitors-hint">
                Separate up to 10 root domains with commas.
              </span>
              {errors.competitors && (
                <span className="field-error" id="project-competitors-error" role="alert">
                  {errors.competitors}
                </span>
              )}
            </div>
            {error && <ErrorBox error={error} />}
            <div className="modal-actions">
              <Dialog.Close asChild>
                <button className="secondary" type="button" disabled={isPending}>
                  Cancel
                </button>
              </Dialog.Close>
              <button type="submit" disabled={isPending}>
                {isPending ? "Creating project…" : "Create project"}
              </button>
            </div>
          </form>
          <Dialog.Close asChild>
            <button
              className="dialog-close"
              type="button"
              aria-label="Close create project dialog"
              disabled={isPending}
            >
              ×
            </button>
          </Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
