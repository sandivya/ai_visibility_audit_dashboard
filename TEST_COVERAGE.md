# Requirements-to-Test Traceability

This matrix maps each important assignment workflow to tests intended to exercise it. A mapped test is traceability evidence, not proof that every edge case is correct or that a particular commit passed. Source-line coverage, PostgreSQL verification, and browser coverage are separate signals.

Evidence levels used here:

- **Backend integration:** FastAPI and service tests run by `pytest`. Local runs default to SQLite for speed; CI is configured to run the same suite against a migrated PostgreSQL schema.
- **PostgreSQL verification:** Migration, restricted-role, row-level-security, and worker smoke commands configured in CI against PostgreSQL.
- **Browser E2E:** Playwright journeys configured to run against the built Docker Compose stack.

The distinction matters: a local SQLite run can demonstrate query scoping, validation, state transitions, and API behavior, but cannot prove PostgreSQL RLS, advisory locks, or `FOR UPDATE SKIP LOCKED` semantics.

## Mandatory workflows

| Requirement | Backend integration coverage | Browser E2E coverage |
| --- | --- | --- |
| Mock login determines the active organization | `test_signed_session_login`, `test_logout_revokes_opaque_server_session` | `switching workspaces visibly preserves tenant isolation`, `sign out revokes the browser session and protects direct routes` |
| Create a project with validated name/domain and server-owned organization | `test_user_can_create_and_list_project`, `test_project_validation`, `test_project_payload_rejects_client_owned_organization` | `an evaluator can validate, create, and open a project` |
| List only the current organization's projects, newest first, with latest audit summary | `test_user_can_create_and_list_project`, `test_project_cursor_pagination`, `test_audit_lifecycle_status_summaries_and_output_endpoints` | `a completed audit exposes evidence, insights, and recommendation workflow` |
| Get an owned project without leaking another organization | `test_cross_org_project_is_hidden` | `direct project and audit URLs remain tenant scoped` |
| Start an owned audit in `queued` state using an idempotency key | `test_audit_lifecycle_status_summaries_and_output_endpoints`, `test_audit_requires_a_bounded_idempotency_key` | `a completed audit exposes evidence, insights, and recommendation workflow` |
| Replay the same key without creating a duplicate; scope keys by organization and project | `test_idempotency_returns_original_audit`, `test_idempotency_key_is_scoped_to_organization_and_project`, `test_concurrent_idempotency_returns_one_audit` | Covered at the API integration layer because the UI intentionally generates keys |
| Process audits asynchronously through valid states | `test_audit_lifecycle_status_summaries_and_output_endpoints`, `test_state_machine_rejects_terminal_transition`, `test_stale_processing_lease_is_reclaimed_after_worker_restart` | Completed-audit scenario observes polling from active to terminal state |
| Persist and display completed audit score, pages, prompts, findings, recommendations, and events | `test_audit_completes_with_evidence`, `test_audit_lifecycle_status_summaries_and_output_endpoints` | `a completed audit exposes evidence, insights, and recommendation workflow` |
| Persist and display failed audits | `test_failed_domain_is_persisted`, `test_worker_retries_then_persists_terminal_failure` | `a failed audit offers a recovery action` |
| List project audit history newest first | `test_audit_lifecycle_status_summaries_and_output_endpoints` | Completed-audit scenario verifies the project history and latest-output rollup |
| Prevent cross-organization access to audits and all nested outputs | `test_cross_org_audit_is_hidden`, `test_cross_org_nested_audit_resources_are_hidden`, `test_recommendation_status_and_finding_filters` | `direct project and audit URLs remain tenant scoped` |
| Provide clear unauthorized, validation, not-found, cross-tenant, and processing errors | Project, audit, enterprise, and hardening integration suites | Validation, not-found, failed-audit, and signed-out route scenarios |
| Keep the dashboard usable on a mobile viewport | N/A | `the project workspace remains usable at a mobile viewport` |

Traceability result: **13/13 listed core workflow areas have at least one mapped automated check**. This is not a claim of 100% behavioral correctness.

The current configured source-coverage gates are:

- Backend: **85% lines** through the `pytest-cov` gate in `pyproject.toml`. This intentionally leaves defensive branches uncovered so the suite can prioritize tenant isolation, concurrency, idempotency, and worker recovery. Thin operational entry modules executed separately by CI (`worker`, restricted-role smoke, refresh, and session-cleanup commands) are excluded from source-line accounting instead of being padded with CLI mocks.
- Frontend: **100% lines, 60% functions, 70% statements, and 65% branches** in `frontend/vitest.config.ts`.

Those percentages are thresholds, not recorded pass results. Inspect the exact revision's configuration and command output when reviewing a submission. CI is configured to run the backend suite against the Alembic-migrated PostgreSQL schema and reset test rows with `TRUNCATE`, preserving schema constraints and policies. It separately applies, downgrades, and reapplies migrations, runs `app.verify_rls`, and executes `app.restricted_role_smoke` through restricted API and worker roles.

## Optional workflow traceability

| Bonus | Intended automated evidence |
| --- | --- |
| Cursor pagination | Project, audit, finding, and nested evidence pagination integration tests; load-more component tests |
| Audit event log | Completed, failed, retry, and worker-recovery integration tests; audit timeline E2E assertion |
| Rate limiting | Atomic concurrency and retry-header integration tests |
| Recommendation status | All four valid statuses, invalid status, cross-tenant denial, optimistic UI success/rollback, and E2E updates |
| Search and filtering | Filter-bound cursor integration tests plus severity, category, project, and audit E2E filtering |
| Docker Compose | CI is configured to build the stack, wait for health checks, and run the browser suite; `docker compose config --quiet` validates configuration syntax |

## Reproducible review procedure

1. Start from a clean clone or worktree of the exact submitted commit.
2. Record `git rev-parse HEAD` and require an empty `git status --short`.
3. Run the backend and frontend commands in `README.md` and retain their exit codes or CI artifacts.
4. Run the PostgreSQL restricted-role and Playwright checks when assessing database isolation or end-to-end claims; do not substitute local SQLite coverage for them.
5. Do not combine results from uncommitted files with claims about the named commit.
