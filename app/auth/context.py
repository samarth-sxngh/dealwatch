"""Authentication context variables and user resolution."""

import logging
import uuid
from contextvars import ContextVar
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import TokenPayload
from app.models.user import User
from app.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)

# Context variables propagated across async task chains
_current_token: ContextVar[TokenPayload | None] = ContextVar("current_token", default=None)
_current_user_id: ContextVar[uuid.UUID | None] = ContextVar("current_user_id", default=None)


def set_current_auth(token: TokenPayload | None, user_id: uuid.UUID | None) -> tuple[Any, Any]:
    """Sets the current request authentication context."""
    tok_token = _current_token.set(token)
    uid_token = _current_user_id.set(user_id)
    return tok_token, uid_token


def reset_current_auth(tokens: tuple[Any, Any]) -> None:
    """Resets the authentication context to prior state."""
    tok_token, uid_token = tokens
    _current_token.reset(tok_token)
    _current_user_id.reset(uid_token)


def get_current_token() -> TokenPayload | None:
    """Returns the validated TokenPayload for the active request, if any."""
    return _current_token.get()


def get_current_user_id() -> uuid.UUID | None:
    """Returns the database User UUID for the active authenticated user, if any."""
    return _current_user_id.get()


# In-memory mapping of oauth_sub to database user UUID to reduce Neon WAN roundtrips
_SUB_TO_USER_ID_CACHE: dict[str, uuid.UUID] = {}


def get_cached_user_id(sub: str) -> uuid.UUID | None:
    """Returns cached user UUID if already mapped during this process lifecycle."""
    return _SUB_TO_USER_ID_CACHE.get(sub)


def clear_user_id_cache() -> None:
    """Clears the in-memory subject cache (useful for tests)."""
    _SUB_TO_USER_ID_CACHE.clear()


async def resolve_or_create_user(token: TokenPayload, session: AsyncSession) -> User:
    """Maps the token subject and email to a persisted User in Neon Postgres."""
    user_repo = UserRepository(session)
    user = await user_repo.get_or_create(
        oauth_sub=token.sub,
        email=token.email,
    )
    _SUB_TO_USER_ID_CACHE[token.sub] = user.id
    return user


def extract_bearer_token(auth_header: str | None) -> str | None:
    """Extracts raw JWT token string from Authorization header.

    Format: 'Bearer <token>' (case-insensitive prefix).
    """
    if not auth_header:
        return None
    parts = auth_header.strip().split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None
