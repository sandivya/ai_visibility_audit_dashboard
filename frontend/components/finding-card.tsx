import Link from "next/link";
import type { Finding } from "@/lib/types";

type FindingCardProps = {
  item: Finding;
  evidenceHref?: string;
  showContext?: boolean;
};

export function FindingCard({ item, evidenceHref, showContext = false }: FindingCardProps) {
  const titleId = `finding-${item.id}`;

  return (
    <article className="result-card finding-card" aria-labelledby={titleId}>
      <div className="finding-card-tags">
        <span className={`tag ${item.severity}`}>{item.severity}</span>
        <span className="category">{item.category.replaceAll("_", " ")}</span>
      </div>
      <h3 id={titleId}>{item.title}</h3>
      <p>{item.description}</p>
      {(showContext || evidenceHref) && (
        <footer className="finding-context">
          {showContext && (
            <div>
              <Link href={`/projects/${item.project_id}`}>{item.project_name}</Link>
              <Link href={`/audits/${item.audit_id}`}>Audit #{item.audit_id.slice(-8)}</Link>
              <time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString()}</time>
            </div>
          )}
          {evidenceHref && (
            <Link className="card-action" href={evidenceHref}>
              Inspect supporting evidence
            </Link>
          )}
        </footer>
      )}
    </article>
  );
}
