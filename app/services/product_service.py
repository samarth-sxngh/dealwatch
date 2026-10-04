"""Product service for identifying, extracting, and normalizing products across retailers."""

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.market import detect_market_from_domain, reconcile_market
from app.domain.matching import normalize_gtin
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


def generate_product_normalized_key(
    gtin: str | None,
    brand: str | None,
    model: str | None,
    variant: str | None,
    title: str,
) -> str:
    """Generates a deterministic deduplication key following the matching hierarchy."""
    clean_gtin = normalize_gtin(gtin)
    if clean_gtin:
        return f"gtin:{clean_gtin}"

    clean_brand = (brand or "").strip().lower().replace(" ", "_")
    clean_model = (model or "").strip().lower().replace(" ", "_")
    clean_variant = (variant or "").strip().lower().replace(" ", "_")

    if clean_brand and clean_model:
        if clean_variant:
            return f"product:{clean_brand}_{clean_model}_{clean_variant}"
        return f"product:{clean_brand}_{clean_model}"

    # Fallback to normalized title slug
    slug = "".join(c if c.isalnum() else "_" for c in title.lower().strip())
    slug = "_".join(filter(None, slug.split("_")))[:60]
    return f"title:{slug}"


class ProductService:
    """Service handling product discovery, identification, and normalization."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.subject_repo = SubjectRepository(session)
        self.source_repo = SourceRepository(session)
        self.offer_repo = OfferRepository(session)
        self.observation_repo = ObservationRepository(session)

    async def identify_product(
        self,
        source_url: str | None = None,
        product_query: str | None = None,
    ) -> dict[str, Any]:
        """Identifies a product from either a retailer URL or text query.

        Fetches and extracts structured page data, detects market/currency,
        and saves or retrieves the Subject and canonical Offer.
        """
        if not source_url and not product_query:
            raise ValueError("Either source_url or product_query must be provided.")

        if source_url:
            return await self._identify_from_url(source_url)
        else:
            return await self._identify_from_query(product_query)  # type: ignore[arg-type]

    async def _identify_from_url(self, source_url: str) -> dict[str, Any]:
        canonical_url = canonicalize_url(source_url)
        market_info = detect_market_from_domain(canonical_url)

        # 1. Fetch page safely with SSRF protections
        fetch_res = await fetcher.fetch(canonical_url)
        if not fetch_res.is_success:
            raise ValueError(f"Failed to fetch product page: {fetch_res.error_message}")

        # 2. Extract structured data via retailer adapter or JSON-LD
        adapter = retailer_registry.get_adapter_for_url(canonical_url)
        extracted = adapter.extract(fetch_res.content, canonical_url) if adapter else None

        if not extracted:
            extracted = extractor.extract(fetch_res.content, base_url=canonical_url)

        # 3. Fallback to LLM if structured extraction missed key details
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
            raise ValueError("Unable to extract product information from the provided page.")

        # Reconcile market and currency
        offer_curr = extracted.primary_offer.currency if extracted.primary_offer else None
        market = reconcile_market(market_info, offer_curr)

        # 4. Generate normalized key & get/create Subject
        normalized_key = generate_product_normalized_key(
            gtin=extracted.gtin,
            brand=extracted.brand,
            model=extracted.model,
            variant=extracted.variant,
            title=extracted.title,
        )

        subject = await self.subject_repo.get_by_normalized_key("products", normalized_key)
        if not subject:
            subject = await self.subject_repo.create_product_subject(
                normalized_key=normalized_key,
                title=extracted.title,
                brand=extracted.brand,
                model=extracted.model,
                variant=extracted.variant,
                gtin=extracted.gtin,
                mpn=extracted.mpn,
                sku=extracted.sku,
                description=extracted.description,
                image_url=extracted.image_url,
                raw_specs=extracted.raw_specs,
            )

        # 5. Look up or create Source entity
        source_name = adapter.name if adapter else (market_info.country or "Retailer")
        source = await self.source_repo.get_or_create(
            domain=adapter.domain if adapter else "unknown",
            name=source_name,
            country=market.country or "US",
            currency=market.currency or "USD",
            vertical="products",
        )

        # 6. Save or update Offer
        primary = extracted.primary_offer
        offer = await self.offer_repo.save_or_update_offer(
            subject_id=subject.id,
            source_id=source.id,
            canonical_url=canonical_url,
            currency=market.currency or (primary.currency if primary else "USD"),
            base_price=primary.base_price if primary else None,
            fees=primary.fees if primary else None,
            taxes=primary.taxes if primary else None,
            discounts=getattr(primary, "discounts", None) if primary else None,
            total_price=primary.total_price if primary else None,
            availability=primary.availability if primary else "unknown",
            condition=primary.condition if primary else "new",
            seller=primary.seller if primary else None,
            match_status="exact",
            matched_on="source_origin",
            price_status=primary.price_status if primary else "ok",
        )

        # 7. Record initial Observation
        check_run_id = f"init-{uuid.uuid4().hex[:8]}"
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

        return {
            "subject_id": str(subject.id),
            "title": subject.product_details.title if subject.product_details else extracted.title,
            "brand": subject.product_details.brand if subject.product_details else extracted.brand,
            "model": subject.product_details.model if subject.product_details else extracted.model,
            "variant": subject.product_details.variant
            if subject.product_details
            else extracted.variant,
            "market_country": market.country,
            "currency": market.currency,
            "market_confidence": market.confidence,
            "clarification_prompt": market.clarification_prompt,
            "observed_price": float(offer.total_price) if offer.total_price is not None else None,
            "availability": offer.availability,
            "source_url": canonical_url,
            "offer_id": str(offer.id),
            "match_status": offer.match_status,
        }

    async def _identify_from_query(self, query: str) -> dict[str, Any]:
        """Identifies or drafts a subject based on a product search query."""
        normalized_key = f"query:{query.lower().strip()}"
        subject = await self.subject_repo.get_by_normalized_key("products", normalized_key)
        if not subject:
            subject = await self.subject_repo.create_product_subject(
                normalized_key=normalized_key,
                title=query.strip(),
            )

        return {
            "subject_id": str(subject.id),
            "title": query.strip(),
            "brand": None,
            "model": None,
            "variant": None,
            "market_country": None,
            "currency": None,
            "market_confidence": "needs_input",
            "clarification_prompt": "Which country should I search in?",
            "observed_price": None,
            "availability": "unknown",
            "source_url": None,
            "offer_id": None,
            "match_status": "exact",
        }
