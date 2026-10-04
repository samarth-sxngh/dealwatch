"""Tests for Phase 10 deployment configuration, container assets, and smoke test CLI."""

import os
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from scripts.smoke_test import run_smoke_tests

REPO_ROOT = Path(__file__).parent.parent


def test_dockerfile_structure_and_security():
    """Validates Dockerfile follows best practices for multi-stage, non-root, and healthcheck."""
    dockerfile_path = REPO_ROOT / "Dockerfile"
    assert dockerfile_path.exists(), "Dockerfile must exist at repository root"

    content = dockerfile_path.read_text(encoding="utf-8")

    # Multi-stage verification
    assert "AS builder" in content, "Dockerfile must use multi-stage build (builder stage)"
    assert "AS runner" in content, "Dockerfile must use multi-stage build (runner stage)"

    # Defense-in-depth: non-root user
    assert "dealwatch" in content, "Must create dedicated dealwatch user"
    assert "USER dealwatch" in content, "Must switch to non-root USER dealwatch before running"

    # Container healthcheck
    assert "HEALTHCHECK" in content, "Dockerfile must specify HEALTHCHECK directive"
    assert "/health" in content, "Healthcheck must target /health"

    # Entrypoint
    assert 'ENTRYPOINT ["/app/scripts/entrypoint.sh"]' in content


def test_dockerignore_configuration():
    """Validates .dockerignore excludes sensitive secrets and development caches."""
    dockerignore_path = REPO_ROOT / ".dockerignore"
    assert dockerignore_path.exists(), ".dockerignore must exist at repository root"

    content = dockerignore_path.read_text(encoding="utf-8")

    assert ".env" in content, ".dockerignore must exclude .env files"
    assert ".venv" in content, ".dockerignore must exclude virtual environments"
    assert ".git" in content, ".dockerignore must exclude .git directory"
    assert "tests" in content, ".dockerignore must exclude tests from production image"


def test_entrypoint_script_semantics():
    """Validates entrypoint.sh has proper shell settings, migrations, and exec semantics."""
    entrypoint_path = REPO_ROOT / "scripts" / "entrypoint.sh"
    assert entrypoint_path.exists(), "scripts/entrypoint.sh must exist"
    assert os.access(entrypoint_path, os.X_OK), "scripts/entrypoint.sh must be executable"

    content = entrypoint_path.read_text(encoding="utf-8")
    assert "set -e" in content, "Must enable set -e for strict error handling"
    assert "alembic upgrade head" in content, "Must run Alembic migrations on startup"
    assert "exec uvicorn app.main:app" in content, "Must exec uvicorn as PID 1"


def test_render_yaml_specification():
    """Validates render.yaml Blueprint syntax and essential configuration properties."""
    render_path = REPO_ROOT / "render.yaml"
    assert render_path.exists(), "render.yaml must exist at repository root"

    content = render_path.read_text(encoding="utf-8")
    assert "type: web" in content
    assert "name: dealwatch" in content
    assert "plan: free" in content
    assert "healthCheckPath: /health" in content
    assert "DATABASE_URL" in content
    assert "sync: false" in content, "Sensitive credentials must use sync: false in render.yaml"


@pytest.mark.asyncio
async def test_smoke_test_cli_passes_against_healthy_service():
    """Validates scripts/smoke_test.py reports success when all endpoints respond 200 OK."""

    # Mock HTTP client responses
    def mock_handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "/health" in url_str:
            return httpx.Response(200, json={"status": "ok", "service": "dealwatch"})
        if "/ready" in url_str:
            return httpx.Response(200, json={"status": "ready", "database": "connected"})
        if "/.well-known/oauth-protected-resource" in url_str:
            return httpx.Response(
                200,
                json={"resource": "https://dealwatch.local/mcp", "scopes_supported": ["openid"]},
            )
        if "/.well-known/oauth-authorization-server" in url_str:
            return httpx.Response(200, json={"issuer": "https://auth.example.com"})
        if "/mcp" in url_str:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text='event: message\ndata: {"jsonrpc":"2.0","result":{"serverInfo":{"name":"DealWatch"}}}\n\n',
            )
        return httpx.Response(404, text="Not Found")

    transport = httpx.MockTransport(mock_handler)
    with patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
        passed = await run_smoke_tests("http://mock-dealwatch.test")
        assert passed is True


@pytest.mark.asyncio
async def test_smoke_test_cli_fails_when_health_endpoint_errors():
    """Validates scripts/smoke_test.py detects and reports failures."""

    def mock_failing_handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "/health" in url_str:
            return httpx.Response(500, text="Internal Server Error")
        return httpx.Response(200, json={"status": "ok"})

    transport = httpx.MockTransport(mock_failing_handler)
    with patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
        passed = await run_smoke_tests("http://failing-dealwatch.test")
        assert passed is False


@pytest.mark.asyncio
async def test_smoke_test_cli_against_real_asgi_app():
    """Validates scripts/smoke_test.py runs end-to-end against the real FastAPI ASGI app."""
    from app.main import app, lifespan

    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        with patch(
            "httpx.AsyncClient",
            return_value=httpx.AsyncClient(transport=transport, base_url="http://test"),
        ):
            passed = await run_smoke_tests("http://test")
            assert passed is True
