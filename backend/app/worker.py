import logging
import secrets
import signal
import socket
import threading
import uuid

from app.config import get_settings
from app.database import engine
from app.observability import configure_logging, configure_tracing
from app.services import (
    record_worker_heartbeat,
    record_worker_poll,
    record_worker_poll_failure,
    remove_worker_heartbeat,
    run_worker_once,
)

logger = logging.getLogger(__name__)


def _heartbeat(worker_id: str, shutdown: threading.Event) -> None:
    settings = get_settings()
    while not shutdown.is_set():
        try:
            record_worker_heartbeat(worker_id)
        except Exception:
            logger.exception("worker_heartbeat_failed", extra={"worker_id": worker_id})
        shutdown.wait(settings.worker_heartbeat_interval_seconds)


def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_tracing(
        f"{settings.otel_service_name}-worker",
        settings.otel_exporter_otlp_traces_endpoint,
        engine,
    )
    worker_id = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
    shutdown = threading.Event()

    def request_shutdown(signum: int, _frame: object) -> None:
        logger.info(
            "audit_worker_shutdown_requested",
            extra={"worker_id": worker_id, "signal": signum},
        )
        shutdown.set()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)

    heartbeat = threading.Thread(
        target=_heartbeat,
        args=(worker_id, shutdown),
        name="worker-heartbeat",
        daemon=True,
    )
    heartbeat.start()
    logger.info("audit_worker_started", extra={"worker_id": worker_id})
    backoff = max(settings.worker_poll_interval_seconds, 0.1)
    try:
        while not shutdown.is_set():
            try:
                worked = run_worker_once(worker_id)
                record_worker_poll(worker_id, worked)
                backoff = max(settings.worker_poll_interval_seconds, 0.1)
                if not worked:
                    shutdown.wait(settings.worker_poll_interval_seconds)
            except Exception:
                logger.exception("audit_worker_loop_failed", extra={"worker_id": worker_id})
                try:
                    record_worker_poll_failure(worker_id)
                except Exception:
                    logger.exception(
                        "worker_poll_failure_record_failed",
                        extra={"worker_id": worker_id},
                    )
                delay = min(backoff, settings.worker_max_backoff_seconds)
                jitter = delay * (secrets.randbelow(201) / 1_000)
                shutdown.wait(delay + jitter)
                backoff = min(delay * 2, settings.worker_max_backoff_seconds)
    finally:
        shutdown.set()
        heartbeat.join(timeout=settings.worker_heartbeat_interval_seconds + 1)
        try:
            remove_worker_heartbeat(worker_id)
        except Exception:
            logger.exception("worker_heartbeat_cleanup_failed", extra={"worker_id": worker_id})
        logger.info("audit_worker_stopped", extra={"worker_id": worker_id})


if __name__ == "__main__":
    run()
