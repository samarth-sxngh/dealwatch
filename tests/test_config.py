"""Unit tests for Settings and environment validation."""

from app.config import Settings


def test_default_settings():
    """Verify default limits and required boundaries match specs."""
    cfg = Settings(
        DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/test",
    )
    assert cfg.MAX_ACTIVE_TRACKERS_PER_USER == 5
    assert cfg.TRACKING_DURATION_DAYS == 14
    assert cfg.CHECK_INTERVAL_HOURS == 24
    assert cfg.MAX_OFFERS_PER_PRODUCT == 10
    assert cfg.LLM_MAX_CALLS_PER_DAY == 50
    assert cfg.FIRECRAWL_MAX_CREDITS == 100
    assert cfg.FETCH_TIMEOUT_SECONDS == 15
    assert cfg.PER_DOMAIN_MIN_DELAY_SECONDS == 2.0


def test_settings_validation_bounds():
    """Verify validation boundaries reject invalid parameters."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(
            DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/test",
            MAX_ACTIVE_TRACKERS_PER_USER=0,  # ge=1
        )

    with pytest.raises(ValidationError):
        Settings(
            DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/test",
            TRACKING_DURATION_DAYS=31,  # le=30
        )
