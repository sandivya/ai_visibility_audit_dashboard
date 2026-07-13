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
from app.seed import seed
from fastapi.testclient import TestClient
from sqlalchemy import select


@pytest.fixture(autouse=True)
def database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    seed()
    yield
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
