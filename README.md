# AI Visibility Audit Dashboard

This dashboard helps teams understand how their brand appears in AI-generated answers. Users can manage projects, run asynchronous visibility audits, inspect supporting evidence, review findings, and track recommendations without exposing data between organizations.

The repository implements the assignment's core workflow with Next.js, FastAPI, PostgreSQL, Alembic, and a separate background worker. It also contains all six optional extensions. Core requirements and optional work are separated below so that bonus breadth is not mistaken for core correctness or time-box adherence.

## Scope and prioritization

### Core review boundary

The core submission is the smallest path that demonstrates the requested senior full-stack concerns:

1. Mock authentication for two organizations, with organization identity derived on the server.
2. Project creation, listing, detail, and audit history.
3. Idempotent audit creation and backend-side asynchronous processing.
4. Explicit queued, processing, completed, and failed states.
5. Persisted pages, prompts, findings, recommendations, and visibility scores.
6. Backend-enforced tenant isolation, validation, understandable errors, migrations, and tests of risky flows.

The additional authentication, worker-recovery, observability, pagination, rate-limiting, recommendation-workflow, and supply-chain controls are useful demonstrations, but they are not prerequisites for judging whether the assignment's core workflow is correct.

### Time-box disclosure and retrospective cut line

The assignment suggested 5-7 hours and recommended attempting only one or two bonuses. The actual effort was about 10 hours, including requirements review, implementation, UI/UX work, tests, optional features, and hardening. This exceeded the requested time box; this README does not recast it as compliant.

With a strict seven-hour cut line, I would retain the core workflow, tenant isolation, state machine, idempotency, critical tests, and reviewer-friendly Docker Compose setup. I would choose the audit event log as the second optional feature and defer cursor pagination, rate limiting, recommendation statuses, global filtering, OIDC/RBAC, extended observability, and supply-chain automation. Implementing all six bonuses increased review surface and was not the most disciplined interpretation of the prompt.

## What is included

| Scope | Area | Implementation |
|---|---|---|
| Core | Product workflow | Projects, competitors, audits, scores, evidence, findings, recommendations, and status history |
| Core | Organization isolation | Server-scoped queries, tenant-safe foreign keys, and forced PostgreSQL row-level security |
| Core | Reliable processing | Durable queue, explicit audit state machine, worker leases, bounded retries, and idempotent audit creation |
| Core | Reviewer UX | Loading, empty, validation, active, completed, failed, and retry states with usable navigation |
| Optional / hardening | Security | Revocable sessions, role-based access, optional OIDC, CSRF/CORS/host controls, CSP, and safe error responses |
| Optional / hardening | Scale and operations | Keyset pagination, persistent rate limiting, health checks, metrics, and optional tracing |
| Verification | Automated checks | Backend, frontend, browser, accessibility, migration, and restricted-role RLS checks are defined in the repository and CI configuration |
| Bonus / delivery | Local stack | Docker Compose, migrations, seed data, environment template, PostgreSQL, API, worker, and frontend |

### Authorship and AI assistance disclosure

I, Sandivya, interpreted the requirements, selected the architecture and scope, directed the implementation, reviewed the resulting behavior, and accepted the final design decisions. AI coding agents across multiple tools generated or revised substantial portions of the application code, tests, and documentation under that direction; I did not manually type every line.

LLM-based reviews were used as one source of feedback, alongside automated checks and manual inspection. They are not presented as independent proof of correctness. This is a process-level disclosure because reliable line-by-line human-versus-agent attribution is not available. I remain accountable for the submitted behavior and trade-offs, while a technical discussion or live change is the appropriate way to verify my independent understanding of the implementation.

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

Compose creates restricted database roles, applies migrations, seeds two evidence-backed completed
demo audits, and starts PostgreSQL, the API, worker, and frontend. Seeding is idempotent: restarting
the stack does not duplicate audits or reset recommendation progress. To stop the application:

```bash
docker compose down
```

> `docker compose down -v` also permanently deletes the local database volume.

## Demo walkthrough

1. Open the dashboard and sign in as `alice@acme.com`.
2. Open the seeded completed audit to review its score, prompt and page evidence, findings,
   recommendations, and event timeline immediately.
3. Start another audit to watch it move from `queued` to `processing` and then a terminal state.
4. Create a project using a valid root domain and optional competitors to exercise the empty state.
5. Use the global findings page to filter by severity, category, project, and audit.
6. Switch to `bob@beta.com` to confirm that each organization sees only its own data.

To review deterministic failure recovery, create a local demo project with `fail` in its domain and
run an audit. The result explains that an unchanged rerun would fail again and routes the user to
create a corrected project. Transient worker failures remain retryable after bounded retries.

### Demo users

Mock authentication is available only when `MOCK_AUTH_ENABLED=true`.

| User | Organization | Role |
|---|---|---|
| `alice@acme.com` | Acme Skincare | Owner |
| `bob@beta.com` | Beta Finance | Owner |

## Manual component setup

Docker Compose is the recommended reviewer path. For manual setup, run the commands below from the repository root. Most commands work in any shell; environment-variable syntax is shown separately for macOS/Linux and Windows PowerShell.

### Database and migrations

```console
docker compose up -d db
docker compose run --rm db-roles
uv sync --locked --dev
```

Set the migration database URL for your shell:

macOS/Linux:

```bash
export DATABASE_URL="postgresql+psycopg://visibility:visibility@127.0.0.1:5432/visibility"
```

Windows PowerShell:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://visibility:visibility@127.0.0.1:5432/visibility"
```

Then apply migrations and seed the database:

```console
cd backend
uv run alembic upgrade head
uv run python -m app.seed
```

### Backend API

In a new terminal opened at the repository root, set the application database URL:

macOS/Linux:

```bash
export DATABASE_URL="postgresql+psycopg://visibility_app:visibility-app-local@127.0.0.1:5432/visibility"
```

Windows PowerShell:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://visibility_app:visibility-app-local@127.0.0.1:5432/visibility"
```

Then start the API:

```console
cd backend
uv run uvicorn app.main:app --reload --port 8000
```

### Background worker

Run in a second terminal from the repository root. First set the worker database URL:

macOS/Linux:

```bash
export DATABASE_URL="postgresql+psycopg://visibility_worker:visibility-worker-local@127.0.0.1:5432/visibility"
```

Windows PowerShell:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://visibility_worker:visibility-worker-local@127.0.0.1:5432/visibility"
```

Then start the worker:

```console
cd backend
uv run python -m app.worker
```

### Frontend

Run in a separate terminal:

```console
cd frontend
npm ci
npm run dev
```

The frontend uses `http://localhost:8000` by default. To use another API URL, set `NEXT_PUBLIC_API_URL` before running `npm run dev`, using the shell-specific syntax shown above.

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

### Simulated evidence and scoring

This take-home does not call a live AI provider or crawler. Every audit response therefore includes
an explicit `simulated-v2` methodology disclosure. Evidence is generated from a versioned digest of
the normalized brand, domain, and order-independent competitor set, so rerunning an unchanged project
produces the same evidence and score. Changing a relevant input or the methodology version can change
the result.

The 100-point demonstration score consists of a 20-point baseline, up to 50 points for prompt brand
mentions, 15 points for healthy page responses, 10 points for descriptive page titles, and 5 points
for prompts without tracked competitor mentions. Findings identify whether their support is page or
prompt evidence, and recommendations link to the related finding when one exists.

### Idempotency, rate limiting, and pagination

Audit creation is idempotent within `(organization, project, idempotency key)`. Concurrent duplicate requests converge on one audit. Organization-level rate limiting is persistent and atomic across API replicas, and `429` responses include `Retry-After` guidance.

Projects, audits, findings, and evidence use signed, scope-bound keyset cursors rather than unbounded or offset-based reads.

### Validation and error handling

Frontend validation provides immediate field guidance, while Pydantic and database constraints remain authoritative. The API uses stable error codes, safe messages, correlation IDs, and appropriate HTTP statuses. The UI presents loading, empty, partial-error, finalizing, completed, and failed states with contextual retry actions.

### UI, accessibility, and observability

The responsive UI presents score context, evidence summaries, competitor coverage, page health, severity, recommendation workflow, and links from diagnosis to action. It includes semantic landmarks, keyboard focus, live status announcements, reduced-motion support, mobile layouts, and automated accessibility checks.

The API and worker emit structured logs. Readiness validates database connectivity, migration state, and RLS coverage; worker health requires both a current heartbeat and a recent successful queue poll. Prometheus metrics and optional OTLP tracing are supported.

## Tests and quality gates

For reproducible evidence, run checks from a clean clone of the exact commit being reviewed. Record the revision with `git rev-parse HEAD` and confirm `git status --short` is empty before attributing results to that revision. Uncommitted files and results from a different checkout are not submission evidence.

```console
uv sync --locked --dev
uv run ruff check backend
uv run ruff format --check backend
uv run mypy backend/app
uv run bandit -q -r backend/app
uv run pytest

cd frontend
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

The test suites target authentication, authorization, tenant isolation, validation, audit lifecycle and recovery, idempotency, concurrency, rate limiting, filtering, pagination, security headers, UI state, mobile behavior, and accessibility. The default backend test fixture uses SQLite for speed, so it does not by itself prove PostgreSQL-specific behavior such as row-level security or `SKIP LOCKED`. The CI workflow is configured to provision PostgreSQL, exercise reversible migrations and restricted roles, build the production frontend, and run the browser suite against the Compose stack.

CI configuration describes intended gates; it is not evidence that a particular commit passed them. Use the checks and artifacts attached to the exact submitted revision, or rerun the commands above, as the authoritative result.

See [TEST_COVERAGE.md](TEST_COVERAGE.md) for requirement-to-test traceability and the boundaries of each evidence type.

## Optional extensions present in the repository

All six optional extensions are present. The assignment recommended choosing only one or two, so this list should be treated as additional implementation surface, not as six independent reasons to overlook the time-box and prioritization trade-off:

1. Signed keyset pagination for projects, audits, findings, and evidence.
2. Append-only audit lifecycle and generated-item events.
3. Atomic organization-level rate limiting with `Retry-After`.
4. Tenant-scoped recommendation workflow states.
5. Finding filters for severity, category, audit, and project in API and UI.
6. Docker Compose for Next.js, FastAPI, PostgreSQL, migrations, seed data, role bootstrap, and workers.

## Assumptions and trade-offs

- AI search, crawling, and scoring are deterministic because no paid provider is configured. A real provider requires SSRF-safe egress, domain validation, timeouts, and cost controls.
- PostgreSQL is the production database and durable queue for this workload. At much higher throughput, processing can move behind a managed queue with a dead-letter queue while PostgreSQL remains the system of record.
- SQLite is used only for fast isolated local tests; PostgreSQL is canonical, and CI is configured to exercise the migrated schema and restricted roles while Docker Compose provides the reviewer stack.
- Public self-registration, billing, and permanent cloud hosting are outside the demonstrated scope.
- TLS termination, managed secrets, private networking, encrypted backups, retention, alert routing, and disaster recovery belong to the deployment platform.

## Production considerations

Production configuration fails closed unless mock authentication and API docs are disabled, secure `__Host-` cookies and strong secrets are used, PostgreSQL runs through restricted roles, origins and hosts are explicit, and OIDC is fully configured. Application containers run as non-root with read-only filesystems, dropped capabilities, PID limits, and `no-new-privileges`.

Before accepting production traffic, run migrations as a separate administrative job, inject secrets at runtime, keep the database private, protect telemetry endpoints, configure session cleanup, and establish backup, restore, retention, monitoring, and incident-response procedures.

## Project notes

- **External services:** No paid AI, search, or crawling services are required.
- **Approximate time spent:** About 10 hours across requirements review, implementation, UI/UX polish, tests, optional features, and hardening. This exceeded the requested 5-7 hours.
- **Provenance:** AI assistance is disclosed above at the process level; no reliable line-by-line attribution log exists.
- **Review revision:** Treat only a named, clean Git commit as the reproducible submission boundary.
