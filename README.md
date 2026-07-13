# VisibilityStack AI Visibility Audit Dashboard

VisibilityStack helps teams understand how their brand appears in AI-generated answers. Users can manage projects, run asynchronous visibility audits, inspect supporting evidence, review findings, and track recommendations without exposing data between organizations.

The application is a complete local product built with Next.js, FastAPI, PostgreSQL, Alembic, and a durable background worker. It implements the full core workflow and all six optional extensions.

## What is included

| Area | Implementation |
|---|---|
| Product workflow | Projects, competitors, audits, scores, evidence, findings, recommendations, and status history |
| Organization isolation | Server-scoped queries, tenant-safe foreign keys, and forced PostgreSQL row-level security |
| Reliable processing | Durable queue, explicit audit state machine, retries, worker leases, and idempotent audit creation |
| Security | Revocable sessions, role-based access, OIDC support, CSRF/CORS/host controls, CSP, and safe error responses |
| Scale | Independent API and worker services, keyset pagination, persistent rate limiting, and bounded polling |
| Quality | Backend, frontend, integration, accessibility, migration, RLS, and supply-chain checks in CI |
| Local delivery | Docker Compose, migrations, seed data, environment template, health checks, and observability |

### Authorship and AI assistance disclosure

Product planning, requirements interpretation, architecture direction, and prioritization were completed by me, Sandivya. Implementation was executed with a mix of AI coding agents across multiple tools under human direction. The work was also reviewed through LLM-as-a-judge evaluations across multiple tools, automated tests, and quality gates.

## Quick start

Docker Desktop with Docker Compose is the only prerequisite.

```bash
docker compose up --build -d
docker compose ps
```

Open:

- Dashboard: `http://localhost:3000`
- Development API documentation: `http://localhost:8000/docs`
- API readiness: `http://localhost:8000/api/health/ready`
- Prometheus metrics: `http://localhost:8000/metrics`

Compose creates restricted database roles, applies migrations, seeds demonstration data, and starts PostgreSQL, the API, worker, and frontend. To stop the application:

```bash
docker compose down
```

> `docker compose down -v` also permanently deletes the local database volume.

## Demo walkthrough

1. Open the dashboard and sign in as `alice@acme.com`.
2. Review the seeded project or create one using a valid root domain and optional competitors.
3. Start an audit and watch it move from `queued` to `processing` and then a terminal state.
4. Review the score, prompt and page evidence, findings, recommendations, and event timeline.
5. Use the global findings page to filter by severity, category, project, and audit.
6. Switch to `bob@beta.com` to confirm that each organization sees only its own data.

To review failure and retry UX, create a local demo project with `fail` in its domain and run an audit.

### Demo users

Mock authentication is available only when `MOCK_AUTH_ENABLED=true`.

| User | Organization | Role |
|---|---|---|
| `alice@acme.com` | Acme Skincare | Owner |
| `bob@beta.com` | Beta Finance | Owner |

## Manual component setup

Docker Compose is the recommended reviewer path. These commands provide the requested component-level setup for Windows PowerShell.

### Database and migrations

```powershell
docker compose up -d db
docker compose run --rm db-roles
uv sync --locked --dev

$env:DATABASE_URL = "postgresql+psycopg://visibility:visibility@127.0.0.1:5432/visibility"
Set-Location backend
uv run alembic upgrade head
uv run python -m app.seed
```

### Backend API

```powershell
$env:DATABASE_URL = "postgresql+psycopg://visibility_app:visibility-app-local@127.0.0.1:5432/visibility"
uv run uvicorn app.main:app --reload --port 8000
```

### Background worker

Run in a second backend terminal:

```powershell
Set-Location backend
$env:DATABASE_URL = "postgresql+psycopg://visibility_worker:visibility-worker-local@127.0.0.1:5432/visibility"
uv run python -m app.worker
```

### Frontend

Run in a separate terminal:

```powershell
Set-Location frontend
npm ci
$env:NEXT_PUBLIC_API_URL = "http://localhost:8000"
npm run dev
```

These credentials are local defaults only. Deployed environments must use unique secrets and the settings documented in `.env.example`.

## Architecture and key decisions

### Organization isolation and authentication

The authenticated server-side session determines `org_id`; identity or organization headers are never trusted. Tenant data is protected by organization-scoped queries, composite tenant foreign keys, and forced PostgreSQL row-level security. Cross-organization and unknown identifiers intentionally return the same `404` response.

Local sessions use random opaque cookies while PostgreSQL stores only token hashes. Sessions support idle and absolute expiry, revocation, activity tracking, and security events. Production supports OIDC Authorization Code flow with PKCE and the `owner`, `admin`, `member`, and read-only `viewer` roles.

### Audit processing and state machine

Starting an audit commits durable work and returns HTTP `202`. An independent worker claims rows safely with `FOR UPDATE SKIP LOCKED`:

```text
queued -> processing -> completed
                     -> failed
```

Worker leases recover abandoned work, transient failures use bounded retries, and final evidence and status commit atomically. PostgreSQL remains the source of truth; the browser polls only lightweight status data while an audit is active.

### Idempotency, rate limiting, and pagination

Audit creation is idempotent within `(organization, project, idempotency key)`. Concurrent duplicate requests converge on one audit. Organization-level rate limiting is persistent and atomic across API replicas, and `429` responses include `Retry-After` guidance.

Projects, audits, findings, and evidence use signed, scope-bound keyset cursors rather than unbounded or offset-based reads.

### Validation and error handling

Frontend validation provides immediate field guidance, while Pydantic and database constraints remain authoritative. The API uses stable error codes, safe messages, correlation IDs, and appropriate HTTP statuses. The UI presents loading, empty, partial-error, finalizing, completed, and failed states with contextual retry actions.

### UI, accessibility, and observability

The responsive UI presents score context, evidence summaries, competitor coverage, page health, severity, recommendation workflow, and links from diagnosis to action. It includes semantic landmarks, keyboard focus, live status announcements, reduced-motion support, mobile layouts, and automated accessibility checks.

The API and worker emit structured logs. Readiness validates database connectivity, migration state, and RLS coverage; worker health requires both a current heartbeat and a recent successful queue poll. Prometheus metrics and optional OTLP tracing are supported.

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

# With the Compose stack running:
npx --no-install playwright install chromium
npm run test:e2e
```

Tests cover authentication, authorization, tenant isolation, validation, audit lifecycle and recovery, idempotency, concurrency, rate limiting, filtering, pagination, security headers, UI state, mobile behavior, and accessibility. CI also verifies reversible migrations, restricted-role RLS, production builds, dependency and secret scans, container vulnerabilities, and software bills of materials.

## Optional extensions

All six optional extensions are implemented:

1. Signed keyset pagination for projects, audits, findings, and evidence.
2. Append-only audit lifecycle and generated-item events.
3. Atomic organization-level rate limiting with `Retry-After`.
4. Tenant-scoped recommendation workflow states.
5. Finding filters for severity, category, audit, and project in API and UI.
6. Docker Compose for Next.js, FastAPI, PostgreSQL, migrations, seed data, role bootstrap, and workers.

## Assumptions and trade-offs

- AI search, crawling, and scoring are deterministic because no paid provider is configured. A real provider requires SSRF-safe egress, domain validation, timeouts, and cost controls.
- PostgreSQL is the production database and durable queue for this workload. At much higher throughput, processing can move behind a managed queue with a dead-letter queue while PostgreSQL remains the system of record.
- SQLite is used only for fast isolated tests; PostgreSQL is canonical and is exercised by CI and Docker Compose.
- Public self-registration, billing, and permanent cloud hosting are outside the demonstrated scope.
- TLS termination, managed secrets, private networking, encrypted backups, retention, alert routing, and disaster recovery belong to the deployment platform.

## Production considerations

Production configuration fails closed unless mock authentication and API docs are disabled, secure `__Host-` cookies and strong secrets are used, PostgreSQL runs through restricted roles, origins and hosts are explicit, and OIDC is fully configured. Application containers run as non-root with read-only filesystems, dropped capabilities, PID limits, and `no-new-privileges`.

Before accepting production traffic, run migrations as a separate administrative job, inject secrets at runtime, keep the database private, protect telemetry endpoints, configure session cleanup, and establish backup, restore, retention, monitoring, and incident-response procedures.

## Project notes

- **External services:** No paid AI, search, or crawling services are required.
- **Approximate time spent:** About 10 hours across requirements review, implementation, UI/UX polish, tests, and enterprise hardening.
