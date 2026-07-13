from datetime import timedelta

from sqlalchemy import func, select

from app.config import get_settings
from app.database import SessionLocal
from app.models import WorkerHeartbeat, utcnow


def healthy() -> bool:
    settings = get_settings()
    cutoff = utcnow() - timedelta(seconds=settings.worker_health_timeout_seconds)
    with SessionLocal() as db:
        healthy_workers = db.scalar(
            select(func.count())
            .select_from(WorkerHeartbeat)
            .where(
                WorkerHeartbeat.last_seen_at >= cutoff,
                WorkerHeartbeat.last_poll_at.is_not(None),
                WorkerHeartbeat.last_poll_at >= cutoff,
            )
        )
        return bool(healthy_workers)


if __name__ == "__main__":
    raise SystemExit(0 if healthy() else 1)
