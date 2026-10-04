"""Unit and integration tests for ChatGPT App Card Widget and MCP UI Resource."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.mcp import mcp_server
from app.mcp.server import WIDGET_PATH, get_dealwatch_widget
from app.mcp.tools import (
    CHATGPT_WIDGET_META,
    find_offers,
    get_tracking_status,
    stop_tracking,
    track_subject,
    update_tracker,
)


@pytest.mark.asyncio
async def test_mcp_ui_resource_registered():
    """Verifies that ui://dealwatch/widget.html is registered as an MCP resource."""
    resources = await mcp_server.list_resources()
    uris = [str(r.uri) for r in resources]
    assert "ui://dealwatch/widget.html" in uris

    resource = next(r for r in resources if str(r.uri) == "ui://dealwatch/widget.html")
    assert resource.name == "DealWatchWidget"
    assert resource.mime_type == "text/html"


@pytest.mark.asyncio
async def test_widget_html_content_and_safety():
    """Verifies the widget HTML is self-contained and includes required ChatGPT App features."""
    html = await get_dealwatch_widget()
    assert WIDGET_PATH.exists()
    assert len(html) > 1000

    # Required UI elements
    assert "dealwatch-card" in html
    assert "offersList" in html
    assert "sparklineSvg" in html
    assert "targetPriceInput" in html
    assert "btnTrack" in html
    assert "btnStop" in html

    # OpenAI Bridge Integration
    assert "window.openai" in html
    assert "window.openai.toolOutput" in html
    assert "window.openai.callTool" in html
    assert "track_subject" in html
    assert "stop_tracking" in html

    # Zero external CDN dependencies / CSP safety
    assert "https://cdn." not in html
    assert "https://unpkg.com" not in html
    assert "https://cdnjs." not in html
    assert '<link rel="stylesheet" href="http' not in html


@pytest.mark.asyncio
async def test_find_offers_returns_chatgpt_meta():
    """Verifies that find_offers attaches the outputTemplate metadata for ChatGPT."""
    with patch("app.mcp.tools.DealService") as mock_service_cls:
        mock_service = AsyncMock()
        mock_service.find_deals.return_value = {
            "subject_id": "test-uuid",
            "product_title": "Sony WH-1000XM5",
            "lowest_verified_price": 24990.0,
            "verified_offers": [],
            "uncertain_offers": [],
        }
        mock_service_cls.return_value = mock_service

        res = await find_offers(subject_id="test-uuid")
        assert res["status"] == "success"
        assert "_meta" in res
        assert res["_meta"] == CHATGPT_WIDGET_META
        assert res["_meta"]["openai/outputTemplate"] == "ui://dealwatch/widget.html"


@pytest.mark.asyncio
async def test_tracking_tools_return_chatgpt_meta():
    """Verifies tracking lifecycle tools attach outputTemplate metadata."""
    demo_user = uuid.uuid4()
    with (
        patch("app.mcp.tools.resolve_effective_user_id", return_value=demo_user),
        patch("app.mcp.tools.TrackingService") as mock_service_cls,
    ):
        mock_service = AsyncMock()
        mock_service.track_product.return_value = {
            "tracker_id": str(uuid.uuid4()),
            "status": "active",
        }
        mock_service.update_tracker.return_value = {
            "tracker_id": str(uuid.uuid4()),
            "status": "updated",
        }
        mock_service.stop_tracking.return_value = {
            "tracker_id": str(uuid.uuid4()),
            "status": "stopped",
        }
        mock_service.get_tracking_status.return_value = {
            "tracker_id": str(uuid.uuid4()),
            "status": "active",
        }
        mock_service_cls.return_value = mock_service

        # track_subject
        res_track = await track_subject(subject_id=str(uuid.uuid4()), offer_ids=[str(uuid.uuid4())])
        assert res_track["status"] in ("success", "active")
        assert res_track.get("_meta") == CHATGPT_WIDGET_META

        # update_tracker
        res_update = await update_tracker(tracker_id=str(uuid.uuid4()), target_price=500.0)
        assert res_update["status"] in ("success", "updated")
        assert res_update.get("_meta") == CHATGPT_WIDGET_META

        # stop_tracking
        res_stop = await stop_tracking(tracker_id=str(uuid.uuid4()))
        assert res_stop["status"] in ("success", "stopped")
        assert res_stop.get("_meta") == CHATGPT_WIDGET_META

        # get_tracking_status
        res_status = await get_tracking_status(tracker_id=str(uuid.uuid4()))
        assert res_status["status"] in ("success", "active")
        assert res_status.get("_meta") == CHATGPT_WIDGET_META
