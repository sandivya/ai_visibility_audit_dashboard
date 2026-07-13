from typing import Any, Protocol, cast

from authlib.integrations.starlette_client import OAuth  # type: ignore[import-untyped]
from fastapi import Request, Response

from app.config import get_settings

settings = get_settings()
oauth = OAuth()

if settings.oidc_enabled:
    oauth.register(
        name="enterprise_oidc",
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        server_metadata_url=settings.oidc_server_metadata_url,
        client_kwargs={
            "scope": settings.oidc_scopes,
            "code_challenge_method": "S256",
        },
    )


class OIDCClient(Protocol):
    server_metadata: dict[str, Any]

    async def authorize_redirect(self, request: Request, redirect_uri: str) -> Response: ...

    async def authorize_access_token(self, request: Request) -> dict[str, Any]: ...


def oidc_client() -> OIDCClient:
    client = oauth.create_client("enterprise_oidc") if settings.oidc_enabled else None
    if client is None:
        raise RuntimeError("OIDC is not configured")
    return cast(OIDCClient, client)
