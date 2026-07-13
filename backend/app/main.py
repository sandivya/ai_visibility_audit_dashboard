import logging
import re
import secrets
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import get_settings
from app.database import engine
from app.observability import configure_logging, configure_tracing
from app.routes import router
from app.schemas import ErrorResponse
from app.services import latest_queue_observation

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

REQUESTS = Counter(
    "visibility_http_requests_total",
    "HTTP requests",
    ("method", "path", "status"),
)
LATENCY = Histogram(
    "visibility_http_request_duration_seconds",
    "HTTP request latency",
    ("method", "path"),
)
QUEUE_DEPTH = Gauge(
    "visibility_audit_queue_depth",
    "Latest audit queue depth observed by a worker",
    ("state",),
)
HEALTHY_WORKERS = Gauge(
    "visibility_healthy_workers",
    "Workers with both a recent process heartbeat and successful queue poll",
)
QUEUE_OBSERVATION_AGE = Gauge(
    "visibility_queue_observation_age_seconds",
    "Age of the latest worker queue observation, or -1 when unavailable",
)

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status_code: {"model": ErrorResponse, "description": description}
    for status_code, description in (
        (400, "Invalid request"),
        (401, "Authentication required"),
        (403, "Forbidden"),
        (404, "Resource not found"),
        (409, "Conflict"),
        (422, "Validation failed"),
        (429, "Rate limit exceeded"),
        (500, "Unexpected server error"),
        (503, "Service unavailable"),
    )
}

app = FastAPI(
    title="VisibilityStack Audit API",
    version="1.0.0",
    docs_url="/docs" if settings.expose_api_docs else None,
    redoc_url="/redoc" if settings.expose_api_docs else None,
    openapi_url="/openapi.json" if settings.expose_api_docs else None,
    responses=ERROR_RESPONSES,
)
configure_tracing(
    settings.otel_service_name,
    settings.otel_exporter_otlp_traces_endpoint,
    engine,
    app,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[item.strip() for item in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Idempotency-Key", "X-Request-Id"],
    expose_headers=["Retry-After", "X-Request-Id"],
)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="oidc_state",
    max_age=600,
    same_site="lax",
    https_only=settings.secure_cookies,
)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=[host.strip() for host in settings.allowed_hosts.split(",") if host.strip()],
)

REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
ALLOWED_ORIGINS = {
    item.strip().rstrip("/") for item in settings.cors_origins.split(",") if item.strip()
}


@app.middleware("http")
async def request_context(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    supplied_request_id = request.headers.get("X-Request-Id", "")
    request_id = (
        supplied_request_id if REQUEST_ID_RE.fullmatch(supplied_request_id) else str(uuid.uuid4())
    )
    request.state.request_id = request_id
    started = time.perf_counter()
    origin = request.headers.get("Origin", "").rstrip("/")
    cross_site = request.headers.get("Sec-Fetch-Site", "").lower() == "cross-site"
    authenticated_write = (
        request.method in UNSAFE_METHODS and settings.session_cookie_name in request.cookies
    )
    invalid_origin = bool(origin) and origin not in ALLOWED_ORIGINS
    missing_production_origin = settings.app_env == "production" and not origin
    response: Response
    if authenticated_write and (cross_site or invalid_origin or missing_production_origin):
        response = error(request, 403, "csrf_rejected", "The request origin is not allowed")
    else:
        response = await call_next(request)
    route = request.scope.get("route")
    route_path = getattr(route, "path", "__unmatched__")
    duration = time.perf_counter() - started
    REQUESTS.labels(request.method, route_path, str(response.status_code)).inc()
    LATENCY.labels(request.method, route_path).observe(duration)
    response.headers["X-Request-Id"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if settings.expose_api_docs and request.url.path in {"/docs", "/redoc"}:
        # FastAPI's development-only documentation loads its bundled UI from jsDelivr.
        # Keep API responses locked down while allowing the advertised reviewer docs to render.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
            "font-src 'self' data: https://fonts.gstatic.com; "
            "img-src 'self' data: https://fastapi.tiangolo.com; "
            "connect-src 'self'; frame-ancestors 'none'"
        )
    else:
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        vary = {
            item.strip() for item in response.headers.get("Vary", "").split(",") if item.strip()
        }
        vary.add("Cookie")
        response.headers["Vary"] = ", ".join(sorted(vary))
    if settings.app_env == "production":
        response.headers["Strict-Transport-Security"] = (
            "max-age=63072000; includeSubDomains; preload"
        )
    logger.info(
        "http_request",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": route_path,
            "status_code": response.status_code,
            "duration_ms": round(duration * 1000, 2),
        },
    )
    return response


def error(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "request_id": request_id}},
    )


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    response = error(request, exc.status_code, f"http_{exc.status_code}", str(exc.detail))
    if exc.headers:
        response.headers.update(exc.headers)
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0]
    location = ".".join(str(part) for part in first.get("loc", [])[1:])
    detail = str(first.get("ctx", {}).get("error") or first["msg"])
    message = f"{location}: {detail}" if location else detail
    return error(request, 422, "validation_error", message)


@app.exception_handler(SQLAlchemyError)
async def database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    logger.exception(
        "database_error",
        exc_info=exc,
        extra={"request_id": getattr(request.state, "request_id", "unknown")},
    )
    return error(request, 503, "database_error", "The database operation could not be completed")


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "unexpected_error",
        exc_info=exc,
        extra={"request_id": getattr(request.state, "request_id", "unknown")},
    )
    return error(request, 500, "internal_error", "An unexpected error occurred")


@app.get("/metrics", include_in_schema=False)
def metrics(request: Request) -> Response:
    if not settings.metrics_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    if settings.app_env == "production":
        configured_token = settings.metrics_bearer_token
        if not configured_token:
            raise HTTPException(status_code=404, detail="Not found")
        supplied = request.headers.get("Authorization", "")
        expected = f"Bearer {configured_token}"
        if not secrets.compare_digest(supplied, expected):
            raise HTTPException(
                status_code=401,
                detail="Metrics authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
    try:
        observation = latest_queue_observation()
        if observation is None:
            QUEUE_DEPTH.labels("queued").set(0)
            QUEUE_DEPTH.labels("processing").set(0)
            QUEUE_DEPTH.labels("retry_wait").set(0)
            HEALTHY_WORKERS.set(0)
            QUEUE_OBSERVATION_AGE.set(-1)
        else:
            QUEUE_DEPTH.labels("queued").set(observation.queued_count)
            QUEUE_DEPTH.labels("processing").set(observation.processing_count)
            QUEUE_DEPTH.labels("retry_wait").set(observation.retry_wait_count)
            HEALTHY_WORKERS.set(observation.healthy_workers)
            QUEUE_OBSERVATION_AGE.set(max(0.0, time.time() - observation.observed_at.timestamp()))
    except SQLAlchemyError:
        logger.exception("queue_metrics_refresh_failed")
        HEALTHY_WORKERS.set(0)
        QUEUE_OBSERVATION_AGE.set(-1)
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


app.include_router(router, prefix="/api")
app.include_router(router, prefix="/api/v1", include_in_schema=False)
