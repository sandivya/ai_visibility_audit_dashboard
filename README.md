# VisibilityStack AI Visibility Audit Dashboard

VisibilityStack is a tenant-isolated implementation of the Senior Full-Stack Engineer take-home assignment. It combines Next.js, FastAPI, PostgreSQL, Alembic, and an independently scalable durable worker. Every mandatory requirement and all six assignment bonuses are implemented.

## Submission notes

- **Paid external services:** None. Audit results are deterministic; the application does not call paid AI, search, or crawling providers.
- **Scope:** The complete core workflow and all six optional bonuses are implemented. Production identity, observability, database isolation, container hardening, and accessible UI behavior are included as additional engineering depth.
- **Approximate time spent:** About 8 hours end-to-end, including requirements review, implementation, UI/UX polish, tests, and enterprise hardening; tracked approximately across multiple working sessions.

## Assumptions

- The take-home is evaluated as a self-contained product demonstration, so page discovery, AI responses, findings, and scores are deterministic fixtures rather than calls to paid or nondeterministic providers.
- A project owns one canonical root domain and an optional set of competitor domains. Inputs are normalized and duplicate competitor entries are deduplicated.
- Local reviewers use the two seeded mock identities. Production deployments use one explicitly configured OIDC provider and pre-provisioned tenant membership; public self-registration is out of scope.
- Audit completion is asynchronous and eventually consistent. The browser may poll lightweight status data, while PostgreSQL remains the source of truth for durable state and evidence.
- PostgreSQL is the production database and queue for the demonstrated workload. SQLite is a test convenience only, not a supported production fallback.
- TLS termination, managed secret storage, network policy, backups, alert routing, and data-retention policy are deployment-platform responsibilities and must be configured for the target environment.

## Quick start

Docker Desktop with Docker Compose is the only prerequisite:

```bash
docker compose up --build -d
docker compose ps
```

Open the dashboard at `http://localhost:3000`. Development-only API documentation is at `http://localhost:8000/docs`, readiness at `/api/health/ready`, and Prometheus metrics at `/metrics`. Ports bind to `127.0.0.1` by default.

Compose creates restricted API and worker database roles, applies the reversible migration, seeds development data, and then starts the API, worker, and web services. Application containers are non-root, read-only, capability-free, PID-limited, and protected by `no-new-privileges`. The digest-pinned PostgreSQL derivative also starts as its unprivileged `postgres` user, drops all Linux capabilities, applies the same privilege-escalation and PID controls, and omits the otherwise-unused privilege-drop binary.

```bash
docker compose logs -f api worker
docker compose down
```

`docker compose down -v` also permanently deletes the database volume.

## Component-level development

The Compose quick start is the canonical reviewer path. To run each component from source on Windows PowerShell, first start PostgreSQL and create the restricted roles:

```powershell
docker compose up -d db
docker compose run --rm db-roles
uv sync --locked --dev
```

Apply migrations and seed the two demonstration organizations with the administrative database role:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://visibility:visibility@127.0.0.1:5432/visibility"
Set-Location backend
uv run alembic upgrade head
uv run python -m app.seed
```

Run the API with the RLS-restricted application role:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://visibility_app:visibility-app-local@127.0.0.1:5432/visibility"
uv run uvicorn app.main:app --reload --port 8000
```

In a second backend terminal, run the independently scalable worker with its purpose-limited cross-tenant role:

```powershell
Set-Location backend
$env:DATABASE_URL = "postgresql+psycopg://visibility_worker:visibility-worker-local@127.0.0.1:5432/visibility"
uv run python -m app.worker
```

In a frontend terminal, install the locked dependencies and run Next.js:

```powershell
Set-Location frontend
npm ci
$env:NEXT_PUBLIC_API_URL = "http://localhost:8000"
npm run dev
```

The environment values above are local-development defaults only. Use `.env.example` and the production validation rules below for any deployed environment.

## Reviewer walkthrough

1. Open `http://localhost:3000` and sign in as `alice@acme.com`.
2. Review the seeded project dashboard, then create a project with a valid root domain.
3. Start an audit. The audit page moves from queued to processing and refreshes automatically until it reaches a terminal state.
4. Review the score narrative and evidence snapshot, then use the jump links to inspect prompt competitor mentions, page responses, findings, recommendations, and the event timeline. The full audit ID is copyable for support.
5. Use the global findings page to combine severity/category filters with server-paginated project and audit selectors, including project name/domain search.
6. To exercise recovery UX, create a project whose domain contains `fail`, start an audit, and use **Retry audit** from the terminal failure state.
7. Sign out and use `bob@beta.com` to verify that the second organization sees only its own data.

## Development identities

Mock authentication is available only when `MOCK_AUTH_ENABLED=true`:

| User | Organization | Role |
|---|---|---|
| `alice@acme.com` | Acme Skincare | owner |
| `bob@beta.com` | Beta Finance | owner |

Login creates a cryptographically random opaque cookie. Only its SHA-256 hash is stored in PostgreSQL. Sessions have idle and absolute expiration, server-side revocation, activity tracking, and security audit events. Logout and user deactivation revoke the server-side session; no identity or organization header is trusted.

## Production authentication and configuration

Production uses OpenID Connect Authorization Code flow with PKCE. Provider tokens are validated and discarded; the application retains only the stable issuer/subject mapping and creates its own revocable session. Users have `owner`, `admin`, `member`, or read-only `viewer` roles.

Provision an OIDC identity using the administrative migration service. `--org-name` bootstraps a new organization and can be omitted for an existing one:

```bash
docker compose run --rm migrate python -m app.provision_user \
  --org org_example \
  --org-name "Example Organization" \
  --email admin@example.com \
  --role owner \
  --issuer https://identity.example.com \
  --subject provider-stable-subject
```

Run the same command with `--inactive` to disable the identity and revoke its active sessions. Provisioning and changes are security-audited.

Copy `.env.example` and supply secrets through the deployment platform. Production startup fails closed unless all of these controls are satisfied:

- `APP_ENV=production`, `MOCK_AUTH_ENABLED=false`, and `EXPOSE_API_DOCS=false`.
- A `postgresql+psycopg` `DATABASE_URL` using the restricted application or worker role; SQLite and administrative database roles are rejected for production API use.
- A unique 32+ character `SESSION_SECRET`; repository defaults are explicitly rejected.
- Unique `POSTGRES_PASSWORD`, `APP_DB_PASSWORD`, and `WORKER_DB_PASSWORD` values. The API and worker never use the PostgreSQL superuser.
- `SECURE_COOKIES=true` and an HTTP cookie name beginning with `__Host-`.
- Explicit HTTPS `CORS_ORIGINS` and `FRONTEND_URL`; wildcard and HTTP origins are rejected.
- `OIDC_SERVER_METADATA_URL`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, and `OIDC_REDIRECT_URI`.
- The public API hostname in `ALLOWED_HOSTS`.

The production migration does not load demonstration data. Keep `OIDC_AUTO_LINK_VERIFIED_EMAIL=false` for explicit identity provisioning; if enabled, only a provider-verified email can link to an existing unlinked user.

Operational numeric settings are bounded and related values are cross-validated at startup: page sizes, connection-pool limits, SQL timeouts, session lifetimes, worker leases and health windows, retry delays, and rate limits fail fast when unsafe or internally inconsistent.

Compose defaults are intentionally local-development values and are not a production deployment manifest. In production, inject configuration and secrets at runtime, run migrations as a one-shot administrative job before application rollout, keep the API and database on private networks, and expose health and telemetry endpoints only to trusted infrastructure.

## Architecture and security boundaries

### Code organization

The Next.js frontend uses App Router pages under `frontend/app`, reusable shell/result controls under `frontend/components`, domain hooks and view models under `frontend/features`, and a typed HTTP/query-key boundary under `frontend/lib`. Feature-oriented project, result, and audit styles layer on a small global design system; unit/component tests sit beside the code they exercise, while evaluator journeys live under `frontend/e2e`.

The FastAPI backend keeps application assembly, middleware, and exception handling in `backend/app/main.py`; a thin aggregate router composes domain routers for auth/health, projects, audits/evidence, and findings/recommendations. SQLAlchemy models and Pydantic contracts are separate, business and worker transitions live in `services.py`, and dedicated modules own authentication, configuration, readiness, observability, pagination, and operational commands. Alembic versions under `backend/alembic` are the only schema-change path.

### Tenant isolation

The authenticated session determines `org_id` on the server. Tenant resources are protected at three layers:

1. Every route scopes owned-resource queries to the authenticated organization, and cross-tenant identifiers return the same 404 as unknown identifiers.
2. Composite foreign keys such as `(org_id, project_id)` and `(org_id, audit_id)` reject inconsistent direct writes.
3. PostgreSQL row-level security is enabled and forced on tenant tables. The non-superuser API role receives a transaction-local tenant context; missing context exposes zero tenant rows. CI verifies RLS while logged in as `visibility_app` and refuses to verify under an administrative role.

The worker has a separate `BYPASSRLS` role because it must claim work across organizations, but it receives only queue, result, event, project-read, and heartbeat grants. Schema migration remains a one-shot administrative responsibility.

### Authentication and web security

OIDC state uses a short-lived signed HTTP-only cookie. Application sessions are opaque, revocable database records with idle and absolute expiry. RBAC protects all writes, and disabling a user immediately revokes active sessions. Authenticated unsafe requests reject disallowed origins and cross-site fetches; production requires an allowed `Origin`.

The API applies credentialed allow-list CORS, trusted-host validation, normalized correlation IDs, stable error envelopes, no-store authenticated responses, HSTS in production, defensive headers, and bounded Prometheus route labels. API failures include a machine-readable code, user-safe message, and correlation identifier. Validation remains field-specific, rate-limit failures include retry guidance, and the frontend keeps actionable failures visible instead of relying on console output. The Next.js middleware generates a per-request CSP nonce, uses `strict-dynamic`, disables framing and object embedding, and marks rendered pages private/no-store.

### Durable audit processing

Starting an audit commits a `queued` row and returns HTTP 202. A separate worker claims rows with `FOR UPDATE SKIP LOCKED`, records leases and attempts, and follows the explicit state machine:

```text
queued -> processing -> completed
                     -> failed
```

Stale leases are reclaimed, transient audit failures use bounded exponential backoff with stable per-attempt jitter, exhausted work becomes a terminal failure, and every transition is recorded. Worker-loop infrastructure errors back off independently. Heartbeats and recent successful queue polls provide the worker health contract. Multiple worker replicas cannot claim the same audit.

PostgreSQL check constraints enforce valid terminal payloads and lease pairs. Output rows and final status are committed atomically. Domains containing `fail` intentionally exercise the deterministic failure path.

### Scale-sensitive API design

Project, audit, finding, and all audit-evidence collections use signed, scope-bound keyset cursors. Audit detail returns bounded initial evidence plus total counts and next cursors; pages, prompts, findings, recommendations, and events each have a dedicated paginated endpoint. The browser polls only the lightweight status resource every two seconds while work is non-terminal and invalidates evidence once processing ends.

Idempotency is enforced by `(org_id, project_id, idempotency_key)`. Organization-scoped PostgreSQL advisory locks make idempotency and rolling-window rate limiting atomic across API replicas. Accepted attempts are persistent, retries consume no additional quota, and 429 responses include `Retry-After`.

A repeated start request with the same organization, project, and idempotency key returns the originally created audit; concurrent duplicates converge on that record without consuming additional quota. The same key remains independent across different projects or organizations. Cross-organization and unknown resource identifiers intentionally share the same not-found response.

### Product UX and accessibility

The UI emphasizes the evaluator's decision path rather than presenting raw CRUD tables. Project cards show exact creation times and tracked competitors; project detail exposes the full comparison set and score movement versus the prior completed audit. Audit detail provides a copyable identifier, terminal-state synchronization feedback, score narrative, mention rate, brand and competitor coverage, page-health cues, finding severity, deep links between diagnosis and action, and an explicit failed-audit recovery path. Evidence summaries are labelled as cues rather than a claim to expose the complete scoring formula.

Loading, empty, partial-error, finalizing, completed, and failed states are distinct. API errors preserve their stable code, correlation identifier, and `Retry-After` guidance; the UI presents a copyable support reference and contextual retries, while requests have bounded timeouts and cancellation. New projects open directly, evidence is hydrated from bounded audit detail instead of immediately refetching duplicate data, active audits poll only lightweight status, and terminal transitions invalidate the relevant cached evidence.

Keyboard-visible focus, semantic landmarks and headings, labelled controls, live status announcements, reduced-motion behavior, responsive tables/cards, mobile navigation, route-specific titles, a branded favicon, and WCAG-oriented color and interaction states are built in. Playwright covers desktop/mobile evaluator journeys and serious/critical axe violations.

### Observability

The API and worker emit structured JSON logs with safe exception handling. Prometheus exposes bounded request counts, latency histograms, queue state counts, queue-observation freshness, and healthy worker counts. Optional OTLP/HTTP settings instrument FastAPI, SQLAlchemy, and worker processing.

API readiness verifies database connectivity, the exact Alembic revision, forced RLS and tenant-policy coverage; production additionally rejects an API database role that is superuser or can bypass RLS. Worker health requires both a current process heartbeat and a recent successful queue poll, so a live-but-stuck worker is not reported healthy.

`METRICS_ENABLED=false` disables `/metrics`. When metrics are enabled, development leaves the endpoint open for the local walkthrough. Production returns 404 unless `METRICS_BEARER_TOKEN` is configured; with a token configured, callers must send `Authorization: Bearer <token>`. Keep that endpoint on an internal route even when bearer protection is enabled.

### Production operations checklist

- Run `alembic upgrade head` as a separate administrative release step, then allow readiness to gate API traffic. Do not grant migration ownership to API or worker roles.
- Size `DATABASE_POOL_SIZE` and `DATABASE_MAX_OVERFLOW` against the database connection budget across every replica. Statement, lock, and idle-transaction timeouts bound database resource usage.
- Rotate the session, OIDC, database, and metrics credentials through the deployment secret manager. Do not bake `.env` files into images.
- Schedule `docker compose run --rm api python -m app.session_cleanup` (or its platform-equivalent command). Each invocation removes one bounded batch of sessions that have remained expired or revoked beyond `SESSION_RETENTION_SECONDS`; tune `SESSION_CLEANUP_BATCH_SIZE` and repeat runs to match volume.
- Alert on readiness failures, worker queue-poll health, stale queue observations, queue depth, terminal audit failures, elevated 429/5xx rates, and database saturation. Scrape metrics through an authenticated internal collector.
- Define encrypted backup/restore drills, security-audit retention, privacy deletion, and disaster-recovery objectives in the deployment platform before accepting production data.

## Tests and quality gates

```powershell
uv sync --locked --dev
uv run ruff check backend
uv run ruff format --check backend
uv run mypy backend/app
uv run bandit -q -r backend/app
uv run pytest

Set-Location frontend
npm ci
npm run test:coverage
npm run lint
npm run format:check
npm run typecheck
npm run build
npm audit --audit-level=high

# With the Compose stack running in another terminal:
npx --no-install playwright install chromium
npm run test:e2e
```

The backend suite covers authentication, opaque session hashing/revocation/expiry, RBAC, CSRF-origin protection, tenant isolation, ownership constraints, state invariants, successful and failed processing, retry recovery, concurrent idempotency and rate limiting, filtering, recommendation ownership, cursor scope, bounded evidence, security headers, metrics cardinality, production configuration, provisioning, and worker health.

CI additionally enforces backend and frontend coverage floors, audits Python and npm dependencies, performs a reversible PostgreSQL `upgrade/check/downgrade/upgrade`, seeds test data, proves RLS under restricted API and worker roles, compiles the production frontend, validates Compose, and runs desktop/mobile browser and accessibility journeys against the full stack.

A separate supply-chain gate scans the repository for vulnerable dependencies, secrets, and configuration errors; builds each runtime image from digest-pinned official bases; fails on actionable high/critical image vulnerabilities; and retains an SPDX JSON SBOM for the PostgreSQL, migration, API, worker, and web images. GitHub Actions are pinned to verified immutable commits, Dependabot monitors actions, uv, npm, Compose, and Docker dependencies, and superseded branch runs are cancelled.

## Assignment bonuses

All six optional bonuses are implemented:

1. Signed keyset pagination for projects, audits, findings, and evidence.
2. Append-only audit lifecycle and generated-item events.
3. Atomic persistent organization-level rate limiting with `Retry-After`.
4. Tenant-scoped recommendation workflow states.
5. Finding filters for severity, category, audit, and project in API and UI.
6. Docker Compose for Next.js, FastAPI, PostgreSQL, migration/seed, role bootstrap, and worker services.

## Deliberate operational boundaries

- AI search, crawling, and scoring are deterministic substitutes because the assignment does not provide a paid provider. Connecting a real crawler requires domain validation, SSRF-safe egress controls, provider timeouts, and cost quotas.
- PostgreSQL is an effective durable queue for this workload and supports horizontal API/worker scaling. High-throughput or long-running production workloads should move the same state machine to a managed queue with a dead-letter queue while PostgreSQL remains the system of record.
- Deployment-specific controls—managed secrets, TLS termination/WAF, encrypted backups and restore drills, retention jobs, dashboards/alerts/SLOs, and staged zero-downtime rollout—belong to the target cloud platform rather than this provider-neutral repository.
- SQLite is used only for fast isolated tests. PostgreSQL is canonical and is exercised separately by CI and the Compose smoke path.
