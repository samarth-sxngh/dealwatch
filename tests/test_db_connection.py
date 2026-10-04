"""Tests for database connectivity and health endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app


@pytest.mark.asyncio
async def test_database_connection(db_session: AsyncSession):
    """Direct query execution on Postgres verifying connectivity."""
    result = await db_session.execute(text("SELECT 1 AS num"))
    row = result.fetchone()
    assert row is not None
    assert row[0] == 1


@pytest.mark.asyncio
async def test_health_endpoints():
    """Verify FastAPI /health and /ready endpoints return 200."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Liveness
        res_health = await client.get("/health")
        assert res_health.status_code == 200
        assert res_health.json()["status"] == "ok"

        # Readiness
        res_ready = await client.get("/ready")
        assert res_ready.status_code == 200
        data = res_ready.json()
        assert data["status"] == "ready"
        assert data["database"] == "connected"
