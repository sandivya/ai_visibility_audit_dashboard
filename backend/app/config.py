from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


def _is_absolute_url(value: str, *, https: bool, origin_only: bool = False) -> bool:
    parsed = urlparse(value)
    if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        return False
    if https and parsed.scheme != "https":
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    if origin_only and (parsed.path not in {"", "/"} or parsed.params or parsed.query):
        return False
    return True


class Settings(BaseSettings):
    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://visibility:visibility@localhost:5432/visibility"
    cors_origins: str = "http://localhost:3000"
    frontend_url: str = "http://localhost:3000"
    allowed_hosts: str = "localhost,127.0.0.1,testserver"
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_max_overflow: int = Field(default=20, ge=0, le=200)
    database_pool_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    database_pool_recycle_seconds: int = Field(default=1_800, ge=60, le=86_400)
    database_statement_timeout_ms: int = Field(default=30_000, ge=100, le=600_000)
    database_lock_timeout_ms: int = Field(default=5_000, ge=50, le=120_000)
    database_idle_transaction_timeout_ms: int = Field(default=60_000, ge=1_000, le=900_000)
    audit_step_delay_seconds: float = Field(default=0.35, ge=0, le=300)
    audit_rate_limit: int = Field(default=3, ge=1, le=10_000)
    audit_rate_window_seconds: int = Field(default=60, ge=1, le=86_400)
    audit_max_attempts: int = Field(default=3, ge=1, le=20)
    audit_lease_seconds: int = Field(default=30, ge=2, le=7_200)
    audit_retry_delay_seconds: float = Field(default=1.0, gt=0, le=3_600)
    audit_retry_max_delay_seconds: float = Field(default=60.0, gt=0, le=86_400)
    audit_retry_jitter_ratio: float = Field(default=0.2, ge=0, le=0.5)
    worker_poll_interval_seconds: float = Field(default=0.5, gt=0, le=60)
    worker_max_backoff_seconds: float = Field(default=30.0, gt=0, le=3_600)
    worker_heartbeat_interval_seconds: float = Field(default=5.0, gt=0, le=300)
    worker_health_timeout_seconds: int = Field(default=30, ge=2, le=3_600)
    cursor_page_size: int = Field(default=20, ge=1, le=500)
    cursor_max_page_size: int = Field(default=100, ge=1, le=500)
    audit_evidence_page_size: int = Field(default=20, ge=1, le=500)
    audit_evidence_max_page_size: int = Field(default=100, ge=1, le=500)
    mock_auth_enabled: bool = True
    session_secret: str = "development-only-change-me"
    session_cookie_name: str = "visibility_session"
    session_same_site: Literal["lax", "strict", "none"] = "lax"
    session_ttl_seconds: int = Field(default=28_800, ge=300, le=2_592_000)
    session_idle_timeout_seconds: int = Field(default=3_600, ge=60, le=604_800)
    session_touch_interval_seconds: int = Field(default=300, ge=10, le=86_400)
    session_retention_seconds: int = Field(default=604_800, ge=300, le=31_536_000)
    session_cleanup_batch_size: int = Field(default=500, ge=1, le=10_000)
    secure_cookies: bool = False
    oidc_server_metadata_url: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_redirect_uri: str | None = None
    oidc_auto_link_verified_email: bool = False
    oidc_scopes: str = "openid profile email"
    expose_api_docs: bool = True
    metrics_enabled: bool = True
    metrics_bearer_token: str | None = None
    log_level: str = "INFO"
    otel_service_name: str = "visibility-audit"
    otel_exporter_otlp_traces_endpoint: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def validate_configuration(self) -> "Settings":
        if not self.session_touch_interval_seconds < self.session_idle_timeout_seconds:
            raise ValueError("SESSION_TOUCH_INTERVAL_SECONDS must be less than the idle timeout")
        if not self.session_idle_timeout_seconds < self.session_ttl_seconds:
            raise ValueError("SESSION_IDLE_TIMEOUT_SECONDS must be less than the session TTL")
        if self.session_retention_seconds < self.session_ttl_seconds:
            raise ValueError("SESSION_RETENTION_SECONDS must be at least the session TTL")
        if self.session_same_site == "none" and not self.secure_cookies:
            raise ValueError("SameSite=None cookies must be secure")
        if self.cursor_page_size > self.cursor_max_page_size:
            raise ValueError("CURSOR_PAGE_SIZE cannot exceed CURSOR_MAX_PAGE_SIZE")
        if self.audit_evidence_page_size > self.audit_evidence_max_page_size:
            raise ValueError("AUDIT_EVIDENCE_PAGE_SIZE cannot exceed AUDIT_EVIDENCE_MAX_PAGE_SIZE")
        if self.audit_retry_delay_seconds > self.audit_retry_max_delay_seconds:
            raise ValueError("The audit retry base delay cannot exceed its maximum delay")
        if self.audit_lease_seconds <= self.audit_step_delay_seconds:
            raise ValueError("AUDIT_LEASE_SECONDS must exceed the maximum simulated audit step")
        if self.worker_max_backoff_seconds < self.worker_poll_interval_seconds:
            raise ValueError("WORKER_MAX_BACKOFF_SECONDS cannot be shorter than the poll interval")
        if self.worker_health_timeout_seconds < 2 * self.worker_heartbeat_interval_seconds:
            raise ValueError("Worker health timeout must cover at least two heartbeat intervals")
        if self.database_lock_timeout_ms >= self.database_statement_timeout_ms:
            raise ValueError("DATABASE_LOCK_TIMEOUT_MS must be shorter than statement timeout")
        if self.database_statement_timeout_ms >= self.database_idle_transaction_timeout_ms:
            raise ValueError(
                "DATABASE_STATEMENT_TIMEOUT_MS must be shorter than idle transaction timeout"
            )

        if self.app_env == "production":
            rejected_secrets = {
                "development-only-change-me",
                "local-compose-session-secret-change-me",
                "replace-with-at-least-32-random-characters",
            }
            if len(self.session_secret) < 32 or self.session_secret in rejected_secrets:
                raise ValueError("SESSION_SECRET must contain at least 32 characters in production")
            if not self.secure_cookies:
                raise ValueError("SECURE_COOKIES must be enabled in production")
            if self.mock_auth_enabled:
                raise ValueError("MOCK_AUTH_ENABLED must be disabled in production")
            if not all(
                (
                    self.oidc_server_metadata_url,
                    self.oidc_client_id,
                    self.oidc_client_secret,
                    self.oidc_redirect_uri,
                )
            ):
                raise ValueError("OIDC metadata URL, client ID, and client secret are required")
            try:
                database = make_url(self.database_url)
            except ArgumentError as exc:
                raise ValueError("DATABASE_URL must be a valid SQLAlchemy URL") from exc
            if database.drivername != "postgresql+psycopg":
                raise ValueError("Production DATABASE_URL must use postgresql+psycopg")
            if not database.password:
                raise ValueError("Production DATABASE_URL must include a database password")
            origins = [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
            if not origins or any(
                origin == "*" or not _is_absolute_url(origin, https=True, origin_only=True)
                for origin in origins
            ):
                raise ValueError("Production CORS origins must be canonical HTTPS origins")
            if not _is_absolute_url(self.frontend_url, https=True, origin_only=True):
                raise ValueError("FRONTEND_URL must be a canonical HTTPS origin in production")
            metadata_url = self.oidc_server_metadata_url or ""
            if not _is_absolute_url(metadata_url, https=True):
                raise ValueError("OIDC_SERVER_METADATA_URL must be an absolute HTTPS URL")
            redirect_uri = self.oidc_redirect_uri or ""
            if not _is_absolute_url(redirect_uri, https=True):
                raise ValueError("OIDC_REDIRECT_URI must be an absolute HTTPS URL")
            redirect = urlparse(redirect_uri)
            if redirect.params or redirect.query:
                raise ValueError("OIDC_REDIRECT_URI cannot contain parameters or a query string")
            if "openid" not in self.oidc_scopes.split():
                raise ValueError("OIDC_SCOPES must include openid")
            if not self.session_cookie_name.startswith("__Host-"):
                raise ValueError("SESSION_COOKIE_NAME must use the __Host- prefix in production")
            rejected_database_credentials = (
                "visibility:visibility@",
                "visibility-app-local@",
                "visibility-worker-local@",
            )
            if any(value in self.database_url for value in rejected_database_credentials):
                raise ValueError("The development database password is not allowed in production")
            if database.password in {
                "visibility",
                "visibility-app-local",
                "visibility-worker-local",
            }:
                raise ValueError("The development database password is not allowed in production")
            if self.expose_api_docs:
                raise ValueError("EXPOSE_API_DOCS must be disabled in production")
            allowed_hosts = [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]
            if not allowed_hosts or "*" in allowed_hosts:
                raise ValueError("ALLOWED_HOSTS must be explicit in production")
            if self.metrics_bearer_token and len(self.metrics_bearer_token) < 32:
                raise ValueError("METRICS_BEARER_TOKEN must contain at least 32 characters")
        return self

    @property
    def oidc_enabled(self) -> bool:
        return bool(
            self.oidc_server_metadata_url and self.oidc_client_id and self.oidc_client_secret
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
