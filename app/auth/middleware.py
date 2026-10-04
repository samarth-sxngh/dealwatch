"""OAuth 2.1 Authentication Middleware for MCP endpoints."""

import logging
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth.context import (
    extract_bearer_token,
    get_cached_user_id,
    reset_current_auth,
    resolve_or_create_user,
    set_current_auth,
)
from app.auth.verifier import TokenVerificationError, token_verifier
from app.config import settings
from app.database import async_session_factory

logger = logging.getLogger(__name__)


def build_www_authenticate_header(
    error: str = "invalid_token",
    description: str = "The access token is invalid or missing.",
) -> str:
    """Constructs RFC 6750 + RFC 9728 compliant WWW-Authenticate challenge header."""
    metadata_url = settings.AUTH_RESOURCE_METADATA_URL
    return (
        f'Bearer error="{error}", '
        f'error_description="{description}", '
        f'resource_metadata="{metadata_url}"'
    )


class OAuth2Middleware(BaseHTTPMiddleware):
    """Middleware enforcing OAuth 2.1 Bearer authentication on protected MCP endpoints."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        path = request.url.path
        auth_header = request.headers.get("Authorization")
        raw_token = extract_bearer_token(auth_header)

        # 1. Bearer Token is provided -> Validate signature & claims
        if raw_token:
            try:
                # Check for test secret bypass in test environment
                test_secret = (
                    getattr(request.state, "test_jwt_secret", None) or token_verifier.test_secret
                )
                token_payload = token_verifier.verify_token(raw_token, test_secret=test_secret)

                # Persist or look up user in Neon Postgres (using in-memory cache to save WAN roundtrips)
                cached_id = get_cached_user_id(token_payload.sub)
                if cached_id is not None:
                    user_id = cached_id
                else:
                    async with async_session_factory() as session:
                        user = await resolve_or_create_user(token_payload, session)
                        await session.commit()
                        user_id = user.id

                # Set auth context for this request task
                auth_tokens = set_current_auth(token_payload, user_id)
                try:
                    return await call_next(request)
                finally:
                    reset_current_auth(auth_tokens)

            except TokenVerificationError as e:
                logger.info("Bearer token verification failed: %s", e)
                challenge = build_www_authenticate_header(
                    error="invalid_token",
                    description=str(e),
                )
                return JSONResponse(
                    status_code=401,
                    content={"error": "invalid_token", "message": str(e)},
                    headers={"WWW-Authenticate": challenge},
                )
            except Exception:
                logger.exception("Unexpected error verifying auth token")
                challenge = build_www_authenticate_header(
                    error="invalid_token",
                    description="Internal authentication error",
                )
                return JSONResponse(
                    status_code=401,
                    content={"error": "invalid_token", "message": "Internal auth error"},
                    headers={"WWW-Authenticate": challenge},
                )

        # 2. No Token provided on protected MCP endpoints
        if settings.AUTH_REQUIRED and path.startswith("/mcp"):
            challenge = build_www_authenticate_header(
                error="invalid_token",
                description="Missing bearer access token. See resource_metadata for authorization servers.",
            )
            return JSONResponse(
                status_code=401,
                content={
                    "error": "unauthorized",
                    "message": "Missing bearer access token",
                    "resource_metadata": settings.AUTH_RESOURCE_METADATA_URL,
                },
                headers={"WWW-Authenticate": challenge},
            )

        # 3. Unauthenticated allowed in development/demo mode
        return await call_next(request)
