function LoadingLabel({ children }: { children: string }) {
  return <span className="sr-only">{children}</span>;
}

function MetricSkeleton({ count = 3 }: { count?: number }) {
  return (
    <div className={`metric-strip skeleton-metrics metrics-${count}`} aria-hidden="true">
      {Array.from({ length: count }, (_, index) => (
        <div key={index}>
          <span className="skeleton-line short" />
          <strong className="skeleton-line medium" />
        </div>
      ))}
    </div>
  );
}

export function ProjectsSkeleton() {
  return (
    <div className="skeleton-region" role="status" aria-busy="true">
      <LoadingLabel>Loading projects</LoadingLabel>
      <MetricSkeleton />
      <div className="project-grid" aria-hidden="true">
        {Array.from({ length: 3 }, (_, index) => (
          <article className="project-card skeleton-card" key={index}>
            <div className="card-head">
              <span className="skeleton-block skeleton-avatar" />
              <span className="skeleton-line short" />
            </div>
            <span className="skeleton-line medium" />
            <span className="skeleton-line short" />
            <div className="competitors">
              <span className="skeleton-line short" />
              <span className="skeleton-line short" />
            </div>
            <footer>
              <span className="skeleton-line medium" />
              <span className="skeleton-block skeleton-dot" />
            </footer>
          </article>
        ))}
      </div>
    </div>
  );
}

export function ProjectDetailSkeleton() {
  return (
    <div className="skeleton-region" role="status" aria-busy="true">
      <LoadingLabel>Loading project details</LoadingLabel>
      <MetricSkeleton count={4} />
      <div className="skeleton-heading" aria-hidden="true">
        <span className="skeleton-line medium" />
      </div>
      <div className="skeleton-table" aria-hidden="true">
        {Array.from({ length: 3 }, (_, index) => (
          <div className="skeleton-table-row" key={index}>
            <span className="skeleton-line medium" />
            <span className="skeleton-line medium" />
            <span className="skeleton-line short" />
          </div>
        ))}
      </div>
    </div>
  );
}

export function AuditHistorySkeleton() {
  return (
    <div className="skeleton-region compact" role="status" aria-busy="true">
      <LoadingLabel>Loading audit history</LoadingLabel>
      <div className="skeleton-table" aria-hidden="true">
        {Array.from({ length: 3 }, (_, index) => (
          <div className="skeleton-table-row" key={index}>
            <span className="skeleton-line medium" />
            <span className="skeleton-line medium" />
            <span className="skeleton-line short" />
          </div>
        ))}
      </div>
    </div>
  );
}

export function AuditDetailSkeleton() {
  return (
    <div className="skeleton-region" role="status" aria-busy="true">
      <LoadingLabel>Loading audit evidence</LoadingLabel>
      <MetricSkeleton count={5} />
      <div className="results-grid" aria-hidden="true">
        {Array.from({ length: 2 }, (_, column) => (
          <section key={column}>
            <div className="skeleton-heading">
              <span className="skeleton-line medium" />
            </div>
            {Array.from({ length: 2 }, (_, index) => (
              <article className="result-card skeleton-card" key={index}>
                <span className="skeleton-line short" />
                <span className="skeleton-line medium" />
                <span className="skeleton-line" />
                <span className="skeleton-line medium" />
              </article>
            ))}
          </section>
        ))}
      </div>
    </div>
  );
}

export function FindingsSkeleton() {
  return (
    <div className="skeleton-region" role="status" aria-busy="true">
      <LoadingLabel>Searching findings</LoadingLabel>
      <div className="finding-list" aria-hidden="true">
        {Array.from({ length: 3 }, (_, index) => (
          <article className="result-card skeleton-card" key={index}>
            <span className="skeleton-line short" />
            <span className="skeleton-line medium" />
            <span className="skeleton-line" />
            <span className="skeleton-line medium" />
          </article>
        ))}
      </div>
    </div>
  );
}
