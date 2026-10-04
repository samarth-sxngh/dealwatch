"""OAuth 2.1 and JWT token models."""

from typing import Any

from pydantic import BaseModel, Field


class TokenPayload(BaseModel):
    """Parsed and validated claims from a JWT access token."""

    sub: str = Field(description="Subject identifier (unique user ID)")
    email: str | None = Field(default=None, description="User email address if present in claims")
    scopes: list[str] = Field(
        default_factory=list, description="OAuth scopes granted to this token"
    )
    iss: str | None = Field(default=None, description="Issuer claim")
    aud: str | list[str] | None = Field(default=None, description="Audience claim")
    exp: int | None = Field(default=None, description="Expiration UNIX timestamp")
    raw_claims: dict[str, Any] = Field(default_factory=dict, description="All raw decoded claims")


class ProtectedResourceMetadata(BaseModel):
    """OAuth 2.0 Protected Resource Metadata conforming to RFC 9728."""

    resource: str = Field(description="The protected resource identifier URL")
    authorization_servers: list[str] = Field(
        default_factory=list,
        description="List of OAuth authorization servers that can issue access tokens for this resource",
    )
    scopes_supported: list[str] = Field(
        default_factory=list,
        description="OAuth scopes supported by this protected resource",
    )
    bearer_methods_supported: list[str] = Field(
        default_factory=lambda: ["header"],
        description="Supported methods for transmitting the bearer token (e.g. 'header')",
    )
    resource_documentation: str | None = Field(
        default=None,
        description="URL to human-readable developer documentation for the resource",
    )
