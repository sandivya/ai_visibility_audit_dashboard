import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime

from app.config import get_settings


class InvalidCursor(ValueError):
    pass


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _cursor_key() -> bytes:
    return hmac.new(
        get_settings().session_secret.encode(), b"ai-visibility-audit-cursor-v1", hashlib.sha256
    ).digest()


def cursor_scope(namespace: str, **values: str | None) -> str:
    """Build a canonical, fixed-size scope without delimiter collision risks."""
    payload = json.dumps(
        {"namespace": namespace, "values": values},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"{namespace}:{hashlib.sha256(payload).hexdigest()}"


def encode_cursor(created_at: datetime, row_id: str, scope: str) -> str:
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    payload = json.dumps(
        {"created_at": created_at.isoformat(), "id": row_id, "scope": scope},
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(_cursor_key(), payload, hashlib.sha256).digest()
    return f"{_encode(payload)}.{_encode(signature)}"


def decode_cursor(cursor: str, expected_scope: str) -> tuple[datetime, str]:
    try:
        if len(cursor) > 1024:
            raise InvalidCursor("Cursor is too large")
        payload_token, signature_token = cursor.split(".", maxsplit=1)
        payload = _decode(payload_token)
        signature = _decode(signature_token)
        expected = hmac.new(_cursor_key(), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise InvalidCursor("Invalid cursor signature")
        values = json.loads(payload)
        created_at = datetime.fromisoformat(values["created_at"])
        row_id = values["id"]
        scope = values["scope"]
        if (
            created_at.tzinfo is None
            or not isinstance(row_id, str)
            or not row_id
            or len(row_id) > 64
            or scope != expected_scope
        ):
            raise InvalidCursor("Invalid cursor values")
        return created_at, row_id
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, InvalidCursor):
            raise
        raise InvalidCursor("Malformed cursor") from exc
