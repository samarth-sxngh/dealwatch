"""Tests for Phase 11 Claude connector assets, stdio runner, and prompt workflows."""

import json
from pathlib import Path

import pytest

from app.mcp import stdio
from scripts.test_claude_prompts import run_claude_workflow_simulation

REPO_ROOT = Path(__file__).parent.parent


def test_claude_desktop_config_example():
    """Validates claude_desktop_config.json.example is well-formed JSON with remote and local targets."""
    config_path = REPO_ROOT / "claude_desktop_config.json.example"
    assert config_path.exists(), "claude_desktop_config.json.example must exist"

    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert "mcpServers" in data
    assert "dealwatch-remote" in data["mcpServers"]
    assert "dealwatch-local" in data["mcpServers"]

    remote_cfg = data["mcpServers"]["dealwatch-remote"]
    assert remote_cfg["command"] == "npx"
    assert "mcp-remote" in remote_cfg["args"]

    local_cfg = data["mcpServers"]["dealwatch-local"]
    assert "app.mcp.stdio" in local_cfg["args"]


def test_claude_integration_documentation():
    """Validates docs/claude_integration.md exists and covers all Claude integration methods."""
    doc_path = REPO_ROOT / "docs" / "claude_integration.md"
    assert doc_path.exists(), "docs/claude_integration.md must exist"

    content = doc_path.read_text(encoding="utf-8")
    assert "Claude Desktop" in content
    assert "Claude Code" in content
    assert "Claude.ai Web" in content
    assert "identify_subject" in content
    assert "find_offers" in content
    assert "track_subject" in content
    assert "cold start" in content.lower()


def test_stdio_runner_callable():
    """Validates app.mcp.stdio has callable main entrypoint."""
    assert hasattr(stdio, "main")
    assert callable(stdio.main)


@pytest.mark.asyncio
async def test_claude_conversational_workflow_simulation():
    """Validates that the 6-flow Claude conversational tool sequence passes."""
    success = await run_claude_workflow_simulation()
    assert success is True
