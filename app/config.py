"""DealWatch Configuration Module."""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/dealwatch",
        description="Async PostgreSQL connection URL (postgresql+asyncpg://...)",
    )
    DATABASE_URL_UNPOOLED: str | None = Field(
        default=None,
        description="Direct/unpooled database connection URL for DDL/migrations if applicable",
    )

    # Application
    ENVIRONMENT: Literal["development", "production", "test"] = "development"
    LOG_LEVEL: str = "INFO"
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000

    # Quotas & Limits (Free-tier guardrails)
    MAX_ACTIVE_TRACKERS_PER_USER: int = Field(default=5, ge=1, le=50)
    TRACKING_DURATION_DAYS: int = Field(default=14, ge=1, le=30)
    CHECK_INTERVAL_HOURS: int = Field(default=24, ge=1, le=168)
    MAX_OFFERS_PER_PRODUCT: int = Field(default=10, ge=1, le=50)
    LLM_MAX_CALLS_PER_DAY: int = Field(default=50, ge=0)
    FIRECRAWL_MAX_CREDITS: int = Field(default=100, ge=0)
    FETCH_TIMEOUT_SECONDS: int = Field(default=15, ge=1, le=60)
    PER_DOMAIN_MIN_DELAY_SECONDS: float = Field(default=2.0, ge=0.0, le=30.0)

    # External Provider Credentials (configured in respective phases)
    GROQ_API_KEY: str | None = None
    GROQ_MODEL: str = "openai/gpt-oss-20b"
    FIRECRAWL_API_KEY: str | None = None
    BREVO_API_KEY: str | None = None
    BREVO_SENDER_EMAIL: str | None = None
    BREVO_SENDER_NAME: str = "DealWatch"

    # OAuth 2.1 (RFC 9728 & RFC 8414 with Descope/WorkOS JWKS - Phase 8)
    AUTH_REQUIRED: bool = Field(
        default=False,
        description="Whether Bearer authentication is strictly enforced on MCP endpoints",
    )
    AUTH_JWKS_URL: str | None = None
    AUTH_ISSUER: str | None = None
    AUTH_AUDIENCE: str | None = None
    AUTH_RESOURCE_ID: str = Field(
        default="https://dealwatch.local/mcp",
        description="Protected resource identifier for RFC 9728",
    )
    AUTH_SCOPES_SUPPORTED: list[str] = Field(
        default_factory=lambda: ["dealwatch:read", "dealwatch:write"]
    )
    AUTH_RESOURCE_METADATA_URL: str = "/.well-known/oauth-protected-resource"
    AUTH_TEST_SECRET: str | None = Field(
        default=None,
        description="Optional symmetric test secret for local test suites without remote JWKS",
    )


settings = Settings()
