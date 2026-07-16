import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_visibility.db")
os.environ["APP_ENV"] = "test"
os.environ["SESSION_SECRET"] = "test-session-secret-with-sufficient-entropy"
os.environ["AUDIT_STEP_DELAY_SECONDS"] = "0"
os.environ.setdefault("AUDIT_RATE_LIMIT", "20")
os.environ["AUDIT_RETRY_DELAY_SECONDS"] = "0.001"

import pytest
from app.auth import create_user_session
from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import User
from app.schema_health import verify_database_readiness
from app.seed import seed
from fastapi.testclient import TestClient
from sqlalchemy import select, text


def _reset_migrated_postgres_data() -> None:
    """Clear test rows without replacing the Alembic-managed schema or its RLS policies."""
    quote = engine.dialect.identifier_preparer.quote
    tables = ", ".join(quote(table.name) for table in Base.metadata.sorted_tables)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture(scope="session", autouse=True)
def migrated_database_schema() -> None:
    if engine.dialect.name != "postgresql":
        return
    with SessionLocal() as db:
        verify_database_readiness(db, get_settings())


@pytest.fixture(autouse=True)
def database():
    if engine.dialect.name == "postgresql":
        _reset_migrated_postgres_data()
    else:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
    seed(include_demo_audits=False)
    yield
    if engine.dialect.name != "postgresql":
        Base.metadata.drop_all(engine)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def alice_headers(database: None) -> dict[str, str]:
    settings = get_settings()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.id == "usr_alice"))
        assert user is not None
        token = create_user_session(db, user, auth_method="test")
    return {"Cookie": f"{settings.session_cookie_name}={token}"}


@pytest.fixture
def bob_headers(database: None) -> dict[str, str]:
    settings = get_settings()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.id == "usr_bob"))
        assert user is not None
        token = create_user_session(db, user, auth_method="test")
    return {"Cookie": f"{settings.session_cookie_name}={token}"}
