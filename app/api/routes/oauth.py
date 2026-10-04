"""OAuth 2.1 Metadata routes (RFC 9728 and RFC 8414)."""

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.auth.context import get_current_token, get_current_user_id
from app.auth.models import ProtectedResourceMetadata
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["OAuth 2.1"])


@router.get(
    "/.well-known/oauth-protected-resource",
    response_model=ProtectedResourceMetadata,
    summary="OAuth 2.0 Protected Resource Metadata (RFC 9728)",
)
async def get_protected_resource_metadata(request: Request) -> ProtectedResourceMetadata:
    """Returns protected resource metadata advertising supported authorization servers and scopes."""
    auth_servers: list[str] = []
    if settings.AUTH_ISSUER:
        auth_servers.append(settings.AUTH_ISSUER)

    # Resolve dynamic resource URL if default is local
    base_url = str(request.base_url).rstrip("/")
    resource_id = (
        f"{base_url}/mcp"
        if "dealwatch.local" in settings.AUTH_RESOURCE_ID
        else settings.AUTH_RESOURCE_ID
    )

    return ProtectedResourceMetadata(
        resource=resource_id,
        authorization_servers=auth_servers,
        scopes_supported=settings.AUTH_SCOPES_SUPPORTED,
        bearer_methods_supported=["header"],
        resource_documentation="https://github.com/samarth-sxngh/dealwatch",
    )


@router.get(
    "/.well-known/oauth-authorization-server",
    summary="OAuth 2.0 Authorization Server pointer (RFC 8414)",
)
async def get_authorization_server_metadata() -> JSONResponse:
    """Provides authorization server metadata or redirect location if configured."""
    if not settings.AUTH_ISSUER:
        return JSONResponse(
            status_code=404,
            content={
                "error": "not_configured",
                "message": "AUTH_ISSUER is not configured. Set AUTH_ISSUER in your environment.",
            },
        )

    return JSONResponse(
        content={
            "issuer": settings.AUTH_ISSUER,
            "jwks_uri": settings.AUTH_JWKS_URL,
            "scopes_supported": settings.AUTH_SCOPES_SUPPORTED,
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
        }
    )


@router.get(
    "/api/v1/auth/me",
    summary="Current authenticated user status",
)
async def get_current_user_info() -> dict[str, Any]:
    """Returns the authenticated user details for the active session/token."""
    token = get_current_token()
    user_id = get_current_user_id()

    if not token or not user_id:
        return {
            "authenticated": False,
            "user_id": None,
            "sub": None,
            "email": None,
            "scopes": [],
        }

    return {
        "authenticated": True,
        "user_id": str(user_id),
        "sub": token.sub,
        "email": token.email,
        "scopes": token.scopes,
    }
