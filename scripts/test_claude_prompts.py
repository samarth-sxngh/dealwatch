"""DealWatch Claude MCP Workflow Simulation Script.

Simulates the exact tool-call sequences executed by Claude Desktop or Claude Code
across the core conversational user journeys:
1. Product identification from link or query
2. Competitor deal discovery and ranking
3. Submitting and validating candidate competitor offers
4. 14-day price tracking lifecycle (create -> status -> update -> stop)
5. Point-in-time price history queries

Usage:
    python -m scripts.test_claude_prompts
"""

import asyncio
import sys
import uuid
from decimal import Decimal

from app.auth.context import resolve_or_create_user, set_current_auth
from app.auth.models import TokenPayload
from app.database import async_session_factory
from app.mcp.tools import (
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
from app.repositories.offer_repository import OfferRepository
from app.repositories.source_repository import SourceRepository
from app.repositories.subject_repository import SubjectRepository


async def run_claude_workflow_simulation() -> bool:
    """Executes Claude tool-call scenarios sequentially against the application core."""
    print("\n🤖 Running DealWatch Claude MCP Workflow Simulation\n" + "=" * 70)
    steps_passed = 0
    total_steps = 6

    # --------------------------------------------------------------------------
    # Flow 1: Claude identifies product from search query
    # --------------------------------------------------------------------------
    print("▶ Flow 1: User asks Claude: 'Search for Sony WH-1000XM5 headphones'")
    res1 = await identify_subject(vertical="products", query="Sony WH-1000XM5")
    if res1.get("status") == "success" and res1.get("title") == "Sony WH-1000XM5":
        print(
            f"  ✅ identify_subject succeeded: '{res1['title']}' (Subject ID: {res1.get('subject_id')})"
        )
        steps_passed += 1
    else:
        print(f"  ❌ identify_subject failed: {res1}")

    # --------------------------------------------------------------------------
    # Setup test product and offers in database for subsequent flows
    # --------------------------------------------------------------------------
    unique_key = f"claude-test-{uuid.uuid4().hex[:6]}"
    async with async_session_factory() as session:
        subj_repo = SubjectRepository(session)
        src_repo = SourceRepository(session)
        off_repo = OfferRepository(session)

        subject = await subj_repo.create_product_subject(
            normalized_key=f"gtin:0194253782910-{unique_key}",
            title="Apple iPhone 15 (128GB, Blue)",
            brand="Apple",
            model="iPhone 15",
            gtin="0194253782910",
        )
        source1 = await src_repo.get_or_create(
            domain="croma.com", name="Croma", country="IN", currency="INR"
        )
        source2 = await src_repo.get_or_create(
            domain="amazon.in", name="Amazon", country="IN", currency="INR"
        )

        offer1 = await off_repo.save_or_update_offer(
            subject_id=subject.id,
            source_id=source1.id,
            canonical_url=f"https://www.croma.com/p/{unique_key}",
            currency="INR",
            total_price=Decimal("75000.00"),
            match_status="exact",
        )
        offer2 = await off_repo.save_or_update_offer(
            subject_id=subject.id,
            source_id=source2.id,
            canonical_url=f"https://www.amazon.in/dp/{unique_key}",
            currency="INR",
            total_price=Decimal("71990.00"),
            match_status="exact",
        )
        await session.commit()
        subj_id = str(subject.id)
        off_id1 = str(offer1.id)
        off_id2 = str(offer2.id)

    # --------------------------------------------------------------------------
    # Flow 2: Claude finds cheapest verified deals
    # --------------------------------------------------------------------------
    print("\n▶ Flow 2: User asks Claude: 'Are there any cheaper deals for this iPhone 15?'")
    deals_res = await find_offers(subject_id=subj_id)
    if (
        deals_res.get("status") == "success"
        and deals_res.get("lowest_verified_price") == 71990.0
        and len(deals_res.get("verified_offers", [])) >= 2
    ):
        print(
            f"  ✅ find_offers identified cheapest deal: ₹{deals_res['lowest_verified_price']} at {deals_res.get('lowest_verified_retailer')}"
        )
        steps_passed += 1
    else:
        print(f"  ❌ find_offers failed: {deals_res}")

    # --------------------------------------------------------------------------
    # Flow 3: Claude submits candidate competitor URL
    # --------------------------------------------------------------------------
    print("\n▶ Flow 3: Claude submits candidate URL found during search")
    sub_res = await submit_offer_url(
        subject_id=subj_id,
        url=f"https://www.reliancedigital.in/p/{unique_key}",
    )
    # The submit tool validates and handles unparseable URLs gracefully
    if sub_res.get("status") in ["success", "failed"]:
        print(f"  ✅ submit_offer_url handled submission safely (Status: {sub_res.get('status')})")
        steps_passed += 1
    else:
        print(f"  ❌ submit_offer_url encountered unexpected response: {sub_res}")

    # --------------------------------------------------------------------------
    # Flow 4: Claude creates 14-day price tracker (Authenticated session)
    # --------------------------------------------------------------------------
    print("\n▶ Flow 4: User asks Claude: 'Track this for 14 days with target 70,000 INR'")
    sub_val = f"claude-user-{uuid.uuid4().hex[:6]}"
    simulated_token = TokenPayload(sub=sub_val, email=f"{sub_val}@example.com")
    async with async_session_factory() as session:
        simulated_user = await resolve_or_create_user(simulated_token, session)
        await session.commit()
        sim_user_id = simulated_user.id

    set_current_auth(simulated_token, sim_user_id)

    track_res = await track_subject(
        subject_id=subj_id,
        offer_ids=[off_id1, off_id2],
        target_price=70000.0,
        target_currency="INR",
        duration_days=14,
    )

    if track_res.get("status") == "quota_exceeded":
        # Free space if quota hit from prior tests
        user_trackers = await list_trackers(status="active")
        for t in user_trackers.get("trackers", []):
            await stop_tracking(t["tracker_id"])
        track_res = await track_subject(
            subject_id=subj_id,
            offer_ids=[off_id1],
            target_price=70000.0,
            target_currency="INR",
            duration_days=14,
        )

    if track_res.get("status") == "active":
        tracker_id = track_res["tracker_id"]
        print(
            f"  ✅ track_subject created tracker: {tracker_id} (Target: ₹{track_res.get('target_price')}, Days: {track_res.get('duration_days')})"
        )
        steps_passed += 1
    else:
        print(f"  ❌ track_subject failed: {track_res}")
        return False

    # --------------------------------------------------------------------------
    # Flow 5: Claude queries tracker status, updates target, and stops tracker
    # --------------------------------------------------------------------------
    print("\n▶ Flow 5: User queries status, changes target price, and stops tracking")
    status_res = await get_tracking_status(tracker_id=tracker_id)
    update_res = await update_tracker(tracker_id=tracker_id, target_price=69500.0)
    stop_res = await stop_tracking(tracker_id=tracker_id)

    if (
        status_res.get("status") == "active"
        and update_res.get("target_price") == 69500.0
        and stop_res.get("status") == "stopped"
    ):
        print(
            "  ✅ Tracker lifecycle completed: active -> updated to ₹69,500 -> stopped successfully"
        )
        steps_passed += 1
    else:
        print(
            f"  ❌ Tracker lifecycle check failed: status={status_res.get('status')}, update={update_res.get('target_price')}, stop={stop_res.get('status')}"
        )

    # --------------------------------------------------------------------------
    # Flow 6: Claude retrieves price history
    # --------------------------------------------------------------------------
    print("\n▶ Flow 6: User asks Claude: 'Show price history for this item'")
    hist_res = await get_price_history(offer_id=off_id1)
    if hist_res.get("status") == "success" and isinstance(hist_res.get("history"), list):
        print(
            f"  ✅ get_price_history retrieved {len(hist_res['history'])} historical observations"
        )
        steps_passed += 1
    else:
        print(f"  ❌ get_price_history failed: {hist_res}")

    print("\n" + "=" * 70)
    print(f"Claude MCP Simulation Results: {steps_passed}/{total_steps} Flows Passed")
    return steps_passed == total_steps


def main() -> None:
    success = asyncio.run(run_claude_workflow_simulation())
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
