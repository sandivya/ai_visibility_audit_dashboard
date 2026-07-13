import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Not found" };

export default function NotFound() {
  return (
    <main className="standalone-state">
      <section className="standalone-card" aria-labelledby="not-found-title">
        <div className="brand standalone-brand">
          <span className="brand-mark" aria-hidden="true">
            V
          </span>
          <span>
            Visibility<span>Stack</span>
          </span>
        </div>
        <p className="eyebrow">404 · Not found</p>
        <h1 id="not-found-title">This view isn’t available</h1>
        <p>The resource may have moved, or your workspace may not have access to it.</p>
        <Link className="button-link" href="/">
          Return to projects
        </Link>
      </section>
    </main>
  );
}
