#!/bin/sh
set -eu

export PGPASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"

psql \
  --host="${DB_HOST:-db}" \
  --username="${POSTGRES_USER:-visibility}" \
  --dbname="${POSTGRES_DB:-visibility}" \
  --set=ON_ERROR_STOP=1 \
  --set=database_name="${POSTGRES_DB:-visibility}" \
  --set=admin_role="${POSTGRES_USER:-visibility}" \
  --set=app_password="${APP_DB_PASSWORD:?APP_DB_PASSWORD is required}" \
  --set=worker_password="${WORKER_DB_PASSWORD:?WORKER_DB_PASSWORD is required}" <<'SQL'
SELECT 'CREATE ROLE visibility_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'visibility_app')
\gexec

SELECT 'CREATE ROLE visibility_worker LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT BYPASSRLS'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'visibility_worker')
\gexec

ALTER ROLE visibility_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD :'app_password';
ALTER ROLE visibility_worker WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT BYPASSRLS PASSWORD :'worker_password';

GRANT CONNECT ON DATABASE :"database_name" TO visibility_app, visibility_worker;
GRANT USAGE ON SCHEMA public TO visibility_app, visibility_worker;

DO $permissions$
BEGIN
  IF to_regclass('public.worker_heartbeats') IS NOT NULL
     AND to_regclass('public.security_audit_events') IS NOT NULL THEN
    REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM visibility_app, visibility_worker;

    GRANT SELECT ON alembic_version, organizations, users, worker_heartbeats TO visibility_app;
    GRANT UPDATE (oidc_issuer, oidc_subject) ON users TO visibility_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON user_sessions TO visibility_app;
    GRANT INSERT ON security_audit_events TO visibility_app;
    GRANT SELECT, INSERT ON projects, audits TO visibility_app;
    GRANT SELECT, INSERT, DELETE ON audit_rate_attempts TO visibility_app;
    GRANT SELECT ON audit_pages, audit_prompts, findings TO visibility_app;
    GRANT SELECT, INSERT ON audit_events TO visibility_app;
    GRANT SELECT ON recommendations TO visibility_app;
    GRANT UPDATE (status, updated_at) ON recommendations TO visibility_app;

    GRANT SELECT ON projects TO visibility_worker;
    GRANT SELECT, INSERT, UPDATE ON audits TO visibility_worker;
    GRANT SELECT, INSERT ON audit_pages, audit_prompts, findings, recommendations, audit_events TO visibility_worker;
    GRANT SELECT, INSERT, UPDATE, DELETE ON worker_heartbeats TO visibility_worker;
  END IF;
END
$permissions$;

ALTER DEFAULT PRIVILEGES FOR ROLE :"admin_role" IN SCHEMA public
  REVOKE ALL ON TABLES FROM visibility_app;
ALTER DEFAULT PRIVILEGES FOR ROLE :"admin_role" IN SCHEMA public
  REVOKE ALL ON SEQUENCES FROM visibility_app;
ALTER DEFAULT PRIVILEGES FOR ROLE :"admin_role" IN SCHEMA public
  REVOKE ALL ON TABLES FROM visibility_worker;
ALTER DEFAULT PRIVILEGES FOR ROLE :"admin_role" IN SCHEMA public
  REVOKE ALL ON SEQUENCES FROM visibility_worker;
SQL
