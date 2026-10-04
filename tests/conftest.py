"""Pytest configuration and async database fixtures."""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import settings


@pytest.fixture(autouse=True)
def configure_test_settings():
    """Guarantees safe defaults across test suites regardless of local .env contents."""
    prev_env = settings.ENVIRONMENT
    prev_auth = settings.AUTH_REQUIRED
    prev_iss = settings.AUTH_ISSUER
    prev_aud = settings.AUTH_AUDIENCE
    prev_jwks = settings.AUTH_JWKS_URL
    prev_secret = settings.AUTH_TEST_SECRET
    prev_brevo = settings.BREVO_API_KEY
    prev_sender = settings.BREVO_SENDER_EMAIL

    settings.ENVIRONMENT = "test"
    settings.AUTH_REQUIRED = False
    settings.AUTH_ISSUER = None
    settings.AUTH_AUDIENCE = None
    settings.AUTH_JWKS_URL = None
    settings.AUTH_TEST_SECRET = None
    settings.BREVO_API_KEY = None
    settings.BREVO_SENDER_EMAIL = "alerts@dealwatch.local"

    yield

    settings.ENVIRONMENT = prev_env
    settings.AUTH_REQUIRED = prev_auth
    settings.AUTH_ISSUER = prev_iss
    settings.AUTH_AUDIENCE = prev_aud
    settings.AUTH_JWKS_URL = prev_jwks
    settings.AUTH_TEST_SECRET = prev_secret
    settings.BREVO_API_KEY = prev_brevo
    settings.BREVO_SENDER_EMAIL = prev_sender


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Function-scoped session with rollback and NullPool for test isolation."""
    # Use NullPool so connections are not shared across event loops
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        poolclass=NullPool,
    )

    connection = await engine.connect()
    transaction = await connection.begin()

    session_maker = async_sessionmaker(
        bind=connection,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    session = session_maker()

    try:
        yield session
    finally:
        await session.close()
        if transaction.is_active:
            await transaction.rollback()
        await connection.close()
        await engine.dispose()
