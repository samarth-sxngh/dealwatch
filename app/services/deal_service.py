"""Deal discovery and competitor offer submission service."""

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.market import detect_market_from_domain, reconcile_market
from app.domain.matching import match_product_with_llm
from app.domain.urls import canonicalize_url
from app.providers.extractor import extractor
from app.providers.fetcher import fetcher
from app.providers.llm import llm_provider
from app.providers.retailers.registry import retailer_registry
from app.repositories.observation_repository import ObservationRepository
from app.repositories.offer_repository import OfferRepository
from app.repositories.source_repository import SourceRepository
from app.repositories.subject_repository import SubjectRepository

logger = logging.getLogger(__name__)


class DealService:
    """Service for discovering and verifying competitor deals."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.subject_repo = SubjectRepository(session)
        self.offer_repo = OfferRepository(session)
        self.source_repo = SourceRepository(session)
        self.observation_repo = ObservationRepository(session)

    async def find_deals(
        self,
        subject_id: uuid.UUID | str,
        market_country: str | None = None,
        currency: str | None = None,
    ) -> dict[str, Any]:
        """Returns verified exact offers sorted by lowest price, listing uncertain offers separately."""
        uid = uuid.UUID(str(subject_id)) if isinstance(subject_id, str) else subject_id
        subject = await self.subject_repo.get_by_id_with_details(uid)
        if not subject:
            raise ValueError(f"Subject '{subject_id}' not found.")

        all_offers = await self.offer_repo.get_offers_for_subject(uid)

        # Filter by market/currency if requested
        if market_country:
            all_offers = [o for o in all_offers if o.source.country == market_country.upper()]
        if currency:
            all_offers = [o for o in all_offers if o.currency == currency.upper()]

        verified_deals: list[dict[str, Any]] = []
        uncertain_deals: list[dict[str, Any]] = []

        for offer in all_offers:
            item = {
                "offer_id": str(offer.id),
                "retailer": offer.source.name,
                "domain": offer.source.domain,
                "url": offer.url_or_deeplink,
                "currency": offer.currency,
                "total_price": float(offer.total_price) if offer.total_price is not None else None,
                "base_price": float(offer.base_price) if offer.base_price is not None else None,
                "availability": offer.availability,
                "condition": offer.condition,
                "match_status": offer.match_status,
                "matched_on": offer.matched_on,
                "match_reasons": offer.match_reasons,
                "price_status": offer.price_status,
                "last_checked_at": offer.last_checked_at.isoformat()
                if offer.last_checked_at
                else None,
            }

            if offer.match_status == "exact":
                verified_deals.append(item)
            elif offer.match_status == "uncertain":
                uncertain_deals.append(item)

        # Verified deals sorted by total_price (nulls last)
        verified_deals.sort(
            key=lambda x: (
                x["total_price"] is None,
                x["total_price"] if x["total_price"] is not None else 0,
            )
        )

        lowest_verified = verified_deals[0] if verified_deals else None

        return {
            "subject_id": str(subject.id),
            "product_title": subject.product_details.title
            if subject.product_details
            else "Product",
            "lowest_verified_price": lowest_verified["total_price"] if lowest_verified else None,
            "lowest_verified_retailer": lowest_verified["retailer"] if lowest_verified else None,
            "lowest_verified_currency": lowest_verified["currency"] if lowest_verified else None,
            "verified_offers_count": len(verified_deals),
            "verified_offers": verified_deals,
            "uncertain_offers_count": len(uncertain_deals),
            "uncertain_offers": uncertain_deals,
        }

    async def submit_offer_url(
        self,
        subject_id: uuid.UUID | str,
        url: str,
    ) -> dict[str, Any]:
        """Validates a candidate competitor URL supplied by host model/user, fetches, verifies exact match, and stores."""
        uid = uuid.UUID(str(subject_id)) if isinstance(subject_id, str) else subject_id
        subject = await self.subject_repo.get_by_id_with_details(uid)
        if not subject:
            raise ValueError(f"Subject '{subject_id}' not found.")

        canonical_url = canonicalize_url(url)
        market_info = detect_market_from_domain(canonical_url)

        # 1. Fetch page safely with SSRF protections
        fetch_res = await fetcher.fetch(canonical_url)
        if not fetch_res.is_success:
            return {
                "accepted": False,
                "reason": f"Failed to fetch competitor URL: {fetch_res.error_message}",
                "canonical_url": canonical_url,
            }

        # 2. Extract structured data
        adapter = retailer_registry.get_adapter_for_url(canonical_url)
        extracted = adapter.extract(fetch_res.content, canonical_url) if adapter else None
        if not extracted:
            extracted = extractor.extract(fetch_res.content, base_url=canonical_url)

        if (not extracted or not extracted.title) and llm_provider.has_quota():
            llm_res = await llm_provider.extract_product_from_text(fetch_res.content)
            if llm_res:
                from app.providers.base import ExtractedOffer, ExtractedProduct

                primary_off = None
                if llm_res.price is not None:
                    primary_off = ExtractedOffer(
                        currency=llm_res.currency or market_info.currency or "USD",
                        base_price=llm_res.price,
                        total_price=llm_res.price,
                        availability=llm_res.availability,
                        condition=llm_res.condition,
                        price_status="ok",
                    )
                extracted = ExtractedProduct(
                    title=llm_res.title,
                    brand=llm_res.brand,
                    model=llm_res.model,
                    variant=llm_res.variant,
                    gtin=llm_res.gtin,
                    mpn=llm_res.mpn,
                    primary_offer=primary_off,
                    all_offers=[primary_off] if primary_off else [],
                )

        if not extracted:
            return {
                "accepted": False,
                "reason": "Could not extract product data from competitor page.",
                "canonical_url": canonical_url,
            }

        # 3. Match Verification against Subject
        details = subject.product_details
        subj_dict = {
            "title": details.title if details else "",
            "brand": details.brand if details else None,
            "model": details.model if details else None,
            "variant": details.variant if details else None,
            "gtin": details.gtin if details else None,
            "mpn": details.mpn if details else None,
            "condition": "new",
            "raw_specs": details.raw_specs if details else {},
        }
        cand_dict = {
            "title": extracted.title,
            "brand": extracted.brand,
            "model": extracted.model,
            "variant": extracted.variant,
            "gtin": extracted.gtin,
            "mpn": extracted.mpn,
            "condition": extracted.primary_offer.condition if extracted.primary_offer else "new",
            "attributes": extracted.raw_specs,
        }

        match_res = await match_product_with_llm(subj_dict, cand_dict, llm_provider)

        # 4. Save Source and Offer
        reconciled_market = reconcile_market(
            market_info, extracted.primary_offer.currency if extracted.primary_offer else None
        )
        source = await self.source_repo.get_or_create(
            domain=adapter.domain if adapter else "unknown",
            name=adapter.name if adapter else (reconciled_market.country or "Competitor"),
            country=reconciled_market.country or "US",
            currency=reconciled_market.currency or "USD",
            vertical="products",
        )

        primary = extracted.primary_offer
        offer = await self.offer_repo.save_or_update_offer(
            subject_id=subject.id,
            source_id=source.id,
            canonical_url=canonical_url,
            currency=reconciled_market.currency or (primary.currency if primary else "USD"),
            base_price=primary.base_price if primary else None,
            fees=primary.fees if primary else None,
            taxes=primary.taxes if primary else None,
            total_price=primary.total_price if primary else None,
            availability=primary.availability if primary else "unknown",
            condition=primary.condition if primary else "new",
            seller=primary.seller if primary else None,
            match_status=match_res.status,
            matched_on=match_res.matched_on,
            match_reasons=match_res.reasons,
            price_status=primary.price_status if primary else "ok",
        )

        # 5. Record Observation if verified or priced
        check_run_id = f"sub-{uuid.uuid4().hex[:8]}"
        await self.observation_repo.record_observation(
            offer_id=offer.id,
            check_run_id=check_run_id,
            currency=offer.currency,
            base_price=offer.base_price,
            fees=offer.fees,
            taxes=offer.taxes,
            total_price=offer.total_price,
            availability=offer.availability,
            price_status=offer.price_status,
        )

        accepted = match_res.status == "exact"
        return {
            "accepted": accepted,
            "offer_id": str(offer.id),
            "match_status": match_res.status,
            "matched_on": match_res.matched_on,
            "reasons": match_res.reasons,
            "observed_price": float(offer.total_price) if offer.total_price is not None else None,
            "currency": offer.currency,
            "retailer": source.name,
            "canonical_url": canonical_url,
        }
