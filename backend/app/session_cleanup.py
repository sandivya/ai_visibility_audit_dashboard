import logging

from app.auth import cleanup_expired_sessions
from app.config import get_settings
from app.database import SessionLocal
from app.observability import configure_logging

logger = logging.getLogger(__name__)


def run() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    with SessionLocal() as db:
        deleted = cleanup_expired_sessions(db)
        db.commit()
    logger.info("expired_sessions_cleaned", extra={"deleted_count": deleted})
    return deleted


if __name__ == "__main__":
    run()
