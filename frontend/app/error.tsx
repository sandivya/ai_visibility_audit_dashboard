"use client";

import Link from "next/link";
import { usePageTitle } from "@/lib/use-page-title";

export default function ErrorPage({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  usePageTitle("Application error");
  return (
    <main className="standalone-state">
      <section className="standalone-card" role="alert" aria-labelledby="error-title">
        <div className="brand standalone-brand">
          <span className="brand-mark" aria-hidden="true">
            V
          </span>
          <span>AI Visibility</span>
        </div>
        <p className="eyebrow">Application error</p>
        <h1 id="error-title">This view couldn’t be loaded</h1>
        <p>Your data is safe. Retry the view, or return to the project dashboard.</p>
        <div className="standalone-actions">
          <button type="button" onClick={reset}>
            Try again
          </button>
          <Link className="button-link secondary" href="/">
            Return to projects
          </Link>
        </div>
      </section>
    </main>
  );
}
