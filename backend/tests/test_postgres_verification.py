from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app import schema_health, verify_rls
from sqlalchemy.exc import DBAPIError, SQLAlchemyError


def _result(*, one: object | None = None, rows: list[object] | None = None) -> MagicMock:
    result = MagicMock()
    result.one.return_value = one
    result.all.return_value = rows or []
    return result


def _verified_db() -> MagicMock:
    db = MagicMock()
    db.__enter__.return_value = db
    db.__exit__.return_value = False
    db.get_bind.return_value.dialect.name = "postgresql"
    policies = [
        SimpleNamespace(tablename=table, qual="org", with_check="org")
        for table in verify_rls.TENANT_TABLES
    ]
    db.execute.side_effect = [_result(one=(False, False)), _result(rows=policies), MagicMock()]
    db.scalar.side_effect = ["visibility_app", *([None] * len(verify_rls.TENANT_MODELS)), None]
    empty_scalars = MagicMock()
    empty_scalars.all.return_value = []
    db.scalars.return_value = empty_scalars
    return db


def _run(monkeypatch: pytest.MonkeyPatch, db: MagicMock) -> MagicMock:
    engine = MagicMock()
    monkeypatch.setenv("RLS_DATABASE_URL", "postgresql+psycopg://restricted")
    monkeypatch.setattr(verify_rls, "create_engine", lambda *_args, **_kwargs: engine)
    monkeypatch.setattr(verify_rls, "Session", lambda _engine: db)
    return engine


def test_rls_verification_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _verified_db()
    engine = _run(monkeypatch, db)
    rejected = MagicMock()
    monkeypatch.setattr(verify_rls, "_expect_rls_rejection", rejected)

    verify_rls.verify()

    assert rejected.call_count == 3
    db.rollback.assert_called_once()
    engine.dispose.assert_called_once()


def test_rls_verification_requires_a_restricted_postgres_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RLS_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="RLS_DATABASE_URL"):
        verify_rls.verify()

    db = _verified_db()
    db.get_bind.return_value.dialect.name = "sqlite"
    _run(monkeypatch, db)
    with pytest.raises(RuntimeError, match="requires PostgreSQL"):
        verify_rls.verify()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("role", "must run as visibility_app"),
        ("capabilities", "can bypass RLS"),
        ("policies", "complete RLS policy"),
        ("no_context", "without context"),
        ("cross_context", "leaked cross-context"),
        ("cross_project", "cross-organization project"),
    ],
)
def test_rls_verification_rejects_unsafe_database_states(
    monkeypatch: pytest.MonkeyPatch, mutation: str, message: str
) -> None:
    db = _verified_db()
    if mutation == "role":
        db.scalar.side_effect = ["postgres"]
    elif mutation == "capabilities":
        db.execute.side_effect = [_result(one=(True, False))]
    elif mutation == "policies":
        db.execute.side_effect = [_result(one=(False, False)), _result(rows=[])]
    elif mutation == "no_context":
        db.scalar.side_effect = ["visibility_app", "org_acme"]
    elif mutation == "cross_context":
        leaked = MagicMock()
        leaked.all.return_value = ["org_beta"]
        db.scalars.return_value = leaked
    else:
        db.scalar.side_effect = [
            "visibility_app",
            *([None] * len(verify_rls.TENANT_MODELS)),
            "prj_beta_demo",
        ]
    _run(monkeypatch, db)

    with pytest.raises(RuntimeError, match=message):
        verify_rls.verify()


def test_rls_write_probe_accepts_only_database_rejection() -> None:
    rejected = MagicMock()
    rejected.begin_nested.return_value.__enter__.return_value = None
    rejected.flush.side_effect = DBAPIError("insert", {}, Exception("denied"))
    verify_rls._expect_rls_rejection(rejected, object())

    accepted = MagicMock()
    accepted.begin_nested.return_value.__enter__.return_value = None
    with pytest.raises(RuntimeError, match="accepted a cross-tenant write"):
        verify_rls._expect_rls_rejection(accepted, object())


def _postgres_readiness_db(scalars: list[object], role: object | None = None) -> MagicMock:
    db = MagicMock()
    db.get_bind.return_value.dialect.name = "postgresql"
    role_result = MagicMock()
    role_result.one_or_none.return_value = role
    db.execute.side_effect = [MagicMock(), role_result]
    db.scalar.side_effect = scalars
    return db


def test_postgres_schema_readiness_accepts_expected_secure_schema() -> None:
    db = _postgres_readiness_db(
        [
            schema_health.EXPECTED_SCHEMA_REVISION,
            len(schema_health.TENANT_TABLES),
            len(schema_health.TENANT_TABLES),
            None,
        ],
        SimpleNamespace(rolsuper=False, rolbypassrls=False),
    )
    settings = SimpleNamespace(app_env="production")

    schema_health.verify_database_readiness(db, settings)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("scalars", "role", "message"),
    [
        (["old"], None, "expected revision"),
        (
            [schema_health.EXPECTED_SCHEMA_REVISION, 0, 0],
            None,
            "row-level security",
        ),
        (
            [
                schema_health.EXPECTED_SCHEMA_REVISION,
                len(schema_health.TENANT_TABLES),
                len(schema_health.TENANT_TABLES),
                "org_acme",
            ],
            None,
            "tenant context",
        ),
        (
            [
                schema_health.EXPECTED_SCHEMA_REVISION,
                len(schema_health.TENANT_TABLES),
                len(schema_health.TENANT_TABLES),
                None,
            ],
            SimpleNamespace(rolsuper=True, rolbypassrls=False),
            "can bypass",
        ),
    ],
)
def test_postgres_schema_readiness_rejects_invalid_states(
    scalars: list[object], role: object | None, message: str
) -> None:
    db = _postgres_readiness_db(scalars, role)
    settings = SimpleNamespace(app_env="production")
    with pytest.raises(schema_health.SchemaNotReady, match=message):
        schema_health.verify_database_readiness(db, settings)  # type: ignore[arg-type]


def test_schema_readiness_wraps_database_errors() -> None:
    db = MagicMock()
    db.execute.side_effect = SQLAlchemyError("offline")
    with pytest.raises(schema_health.SchemaNotReady, match="verification failed"):
        schema_health.verify_database_readiness(  # type: ignore[arg-type]
            db, SimpleNamespace(app_env="test")
        )
