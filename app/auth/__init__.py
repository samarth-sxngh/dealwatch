"""Authentication package exporting verifier, middleware, and context helpers."""

from app.auth.context import (
    extract_bearer_token,
    get_current_token,
    get_current_user_id,
    reset_current_auth,
    resolve_or_create_user,
    set_current_auth,
)
from app.auth.middleware import OAuth2Middleware, build_www_authenticate_header
from app.auth.models import ProtectedResourceMetadata, TokenPayload
from app.auth.verifier import JWKSVerifier, TokenVerificationError, token_verifier

__all__ = [
    "JWKSVerifier",
    "OAuth2Middleware",
    "ProtectedResourceMetadata",
    "TokenPayload",
    "TokenVerificationError",
    "build_www_authenticate_header",
    "extract_bearer_token",
    "get_current_token",
    "get_current_user_id",
    "reset_current_auth",
    "resolve_or_create_user",
    "set_current_auth",
    "token_verifier",
]
