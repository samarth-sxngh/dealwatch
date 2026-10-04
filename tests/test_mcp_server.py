"""Integration and unit tests for DealWatch MCP Server tools and Streamable HTTP transport."""

import uuid
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import async_session_factory
from app.main import app, lifespan
from app.mcp import mcp_server
from app.mcp.tools import (
    compare_quotes,
    find_offers,
    get_price_history,
    get_tracking_status,
    identify_subject,
    list_trackers,
    stop_tracking,
    submit_offer_url,
    track_subject,
    update_tracker,
)
from app.providers.base import FetchResult
from app.providers.fetcher import fetcher
from app.repositories.offer_repository import OfferRepository
from app.repositories.source_repository import SourceRepository
from app.repositories.subject_repository import SubjectRepository

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def read_fixture(filename: str) -> str:
    path = FIXTURES_DIR / filename
    return path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_mcp_streamable_http_initialization():
    """Tests the Streamable HTTP transport at /mcp responds to JSON-RPC initialize."""
    async with (
        lifespan(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client,
    ):
        init_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"},
            },
        }
        res = await client.post(
            "/mcp",
            json=init_payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
        assert res.status_code == 200
        assert "text/event-stream" in res.headers.get("content-type", "")
        assert "DealWatch" in res.text


@pytest.mark.asyncio
async def test_mcp_registered_tools_catalog():
    """Verifies that all 10 tools required by Section 6 and 10B are registered on MCPServer."""
    tools = await mcp_server.list_tools()
    tool_names = {t.name for t in tools}

    expected_tools = {
        "identify_subject",
        "find_offers",
        "submit_offer_url",
        "track_subject",
        "update_tracker",
        "stop_tracking",
        "get_tracking_status",
        "list_trackers",
        "get_price_history",
        "compare_quotes",
    }

    assert expected_tools.issubset(tool_names)


@pytest.mark.asyncio
async def test_tool_identify_subject_from_url_and_query():
    # 1. URL identification
    html_content = read_fixture("croma_iphone.html")
    mock_url = f"https://www.croma.com/p/{uuid.uuid4().hex[:8]}"

    mock_result = FetchResult(
        url=mock_url,
        status_code=200,
        content=html_content,
        content_type="text/html",
        is_success=True,
    )

    with patch.object(fetcher, "fetch", new_callable=AsyncMock, return_value=mock_result):
        res = await identify_subject(vertical="products", url=mock_url)

    assert res["status"] == "success"
    assert res["title"] == "Apple iPhone 15 (128GB, Blue)"
    assert res["brand"] == "Apple"
    assert res["currency"] == "INR"
    assert res["observed_price"] == 71990.0
    assert res["subject_id"] is not None
    assert res["offer_id"] is not None

    # 2. Search query identification
    res_query = await identify_subject(vertical="products", query="Sony WH-1000XM5")
    assert res_query["status"] == "success"
    assert res_query["title"] == "Sony WH-1000XM5"
    assert res_query["market_confidence"] == "needs_input"

    # 3. Invalid inputs
    res_invalid = await identify_subject(vertical="products")
    assert res_invalid["status"] == "failed"

    res_unsupported = await identify_subject(vertical="crypto")
    assert res_unsupported["supported"] is False


@pytest.mark.asyncio
async def test_tool_find_offers_and_submit_candidate_url():
    async with async_session_factory() as session:
        subject_repo = SubjectRepository(session)
        source_repo = SourceRepository(session)
        offer_repo = OfferRepository(session)

        # Create test subject with GTIN
        subject = await subject_repo.create_product_subject(
            normalized_key=f"gtin:0194253782910-{uuid.uuid4().hex[:4]}",
            title="Apple iPhone 15 (128GB, Blue)",
            brand="Apple",
            model="iPhone 15",
            gtin="0194253782910",
            mpn="MTP43HN/A",
        )
        source = await source_repo.get_or_create(
            domain="amazon.in", name="Amazon", country="IN", currency="INR"
        )
        await offer_repo.save_or_update_offer(
            subject_id=subject.id,
            source_id=source.id,
            canonical_url=f"https://www.amazon.in/dp/{uuid.uuid4().hex[:10]}",
            currency="INR",
            total_price=Decimal("74999.00"),
            match_status="exact",
        )
        await session.commit()
        subj_id = str(subject.id)

    # 1. Host model submits competitor URL (Croma @ 71,990 INR)
    croma_html = read_fixture("croma_iphone.html")
    croma_cand_url = f"https://www.croma.com/p/{uuid.uuid4().hex[:8]}"
    mock_res = FetchResult(
        url=croma_cand_url,
        status_code=200,
        content=croma_html,
        content_type="text/html",
        is_success=True,
    )
    with patch.object(fetcher, "fetch", new_callable=AsyncMock, return_value=mock_res):
        sub_res = await submit_offer_url(
            subject_id=subj_id,
            url=croma_cand_url,
        )

    assert sub_res["status"] == "success"
    assert sub_res["accepted"] is True
    assert sub_res["match_status"] == "exact"
    assert sub_res["observed_price"] == 71990.0

    # 2. Find offers returns lowest verified price first
    deals_res = await find_offers(subject_id=subj_id)
    assert deals_res["status"] == "success"
    assert deals_res["lowest_verified_price"] == 71990.0
    assert len(deals_res["verified_offers"]) == 2
    assert deals_res["verified_offers"][0]["total_price"] == 71990.0
    assert deals_res["verified_offers"][1]["total_price"] == 74999.0


@pytest.mark.asyncio
async def test_tool_tracking_lifecycle_and_quota_management():
    async with async_session_factory() as session:
        subject_repo = SubjectRepository(session)
        source_repo = SourceRepository(session)
        offer_repo = OfferRepository(session)

        subject = await subject_repo.create_product_subject(
            normalized_key=f"track-sub-{uuid.uuid4().hex[:6]}",
            title="Gaming Laptop",
        )
        source = await source_repo.get_or_create(
            domain="croma.com", name="Croma", country="IN", currency="INR"
        )
        offer = await offer_repo.save_or_update_offer(
            subject_id=subject.id,
            source_id=source.id,
            canonical_url=f"https://www.croma.com/p/{uuid.uuid4().hex[:8]}",
            currency="INR",
            total_price=Decimal("95000.00"),
            match_status="exact",
        )
        await session.commit()
        subj_id = str(subject.id)
        off_id = str(offer.id)

    # 1. Start tracking job
    track_res = await track_subject(
        subject_id=subj_id,
        offer_ids=[off_id],
        target_price=90000.0,
        target_currency="INR",
        duration_days=14,
    )

    # Check if quota exceeded or success
    if track_res["status"] == "quota_exceeded":
        # Free up by stopping existing trackers
        list_res = await list_trackers(status="active")
        for t in list_res["trackers"]:
            await stop_tracking(t["tracker_id"])
        # Retry track_subject
        track_res = await track_subject(
            subject_id=str(subject.id),
            offer_ids=[str(offer.id)],
            target_price=90000.0,
            target_currency="INR",
            duration_days=14,
        )

    assert track_res["status"] == "active"
    tracker_id = track_res["tracker_id"]
    assert track_res["target_price"] == 90000.0

    # 2. Get tracking status
    status_res = await get_tracking_status(tracker_id=tracker_id)
    assert status_res["status"] == "active"
    assert status_res["product_title"] == "Gaming Laptop"
    assert len(status_res["tracked_offers"]) == 1

    # 3. Update tracker settings
    update_res = await update_tracker(tracker_id=tracker_id, target_price=88000.0)
    assert update_res["status"] == "active"
    assert update_res["target_price"] == 88000.0

    # 4. List trackers
    all_trackers = await list_trackers(status="active")
    assert all_trackers["status"] == "success"
    assert any(t["tracker_id"] == tracker_id for t in all_trackers["trackers"])

    # 5. Stop tracking
    stop_res = await stop_tracking(tracker_id=tracker_id)
    assert stop_res["status"] == "stopped"

    # Status is now stopped
    refreshed_status = await get_tracking_status(tracker_id=tracker_id)
    assert refreshed_status["status"] == "stopped"


@pytest.mark.asyncio
async def test_tool_get_price_history():
    async with async_session_factory() as session:
        subject_repo = SubjectRepository(session)
        source_repo = SourceRepository(session)
        offer_repo = OfferRepository(session)

        subject = await subject_repo.create_product_subject(
            normalized_key=f"hist-sub-{uuid.uuid4().hex[:6]}",
            title="Wireless Earbuds",
        )
        source = await source_repo.get_or_create(
            domain="amazon.in", name="Amazon", country="IN", currency="INR"
        )
        offer = await offer_repo.save_or_update_offer(
            subject_id=subject.id,
            source_id=source.id,
            canonical_url=f"https://www.amazon.in/dp/{uuid.uuid4().hex[:8]}",
            currency="INR",
            total_price=Decimal("3999.00"),
            match_status="exact",
        )
        await session.commit()
        off_id = str(offer.id)

    # Query history
    hist_res = await get_price_history(offer_id=off_id)
    assert hist_res["status"] == "success"
    assert hist_res["offer_id"] == str(offer.id)
    assert isinstance(hist_res["history"], list)


@pytest.mark.asyncio
async def test_tool_compare_quotes_section_10b():
    res = await compare_quotes(
        vertical="flights", origin="BOM", destination="DEL", date="2026-11-01"
    )
    assert res["status"] == "not_implemented"
    assert res["supported"] is False
    assert "Phase 14" in res["message"]
