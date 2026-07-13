from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
is_sqlite = settings.database_url.startswith("sqlite")
connect_args: dict[str, object] = {"check_same_thread": False} if is_sqlite else {}
engine_options: dict[str, Any] = {
    "pool_pre_ping": True,
    "connect_args": connect_args,
}
if settings.database_url.startswith("postgresql"):
    connect_args["options"] = " ".join(
        (
            f"-c statement_timeout={settings.database_statement_timeout_ms}",
            f"-c lock_timeout={settings.database_lock_timeout_ms}",
            "-c idle_in_transaction_session_timeout="
            f"{settings.database_idle_transaction_timeout_ms}",
        )
    )
    engine_options.update(
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout_seconds,
        pool_recycle=settings.database_pool_recycle_seconds,
        pool_use_lifo=True,
    )
engine = create_engine(settings.database_url, **engine_options)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


if is_sqlite:

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def set_tenant_context(session: Session, org_id: str) -> None:
    """Bind PostgreSQL RLS policies to one organization for this transaction."""
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text("SELECT set_config('app.current_org_id', :org_id, true)"),
            {"org_id": org_id},
        )
