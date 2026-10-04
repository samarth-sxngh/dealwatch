"""Structured page data parser using extruct (JSON-LD, microdata) and OpenGraph fallback."""

import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any

import extruct
from bs4 import BeautifulSoup

from app.domain.matching import normalize_gtin
from app.providers.base import ExtractedOffer, ExtractedProduct

logger = logging.getLogger(__name__)


def normalize_availability(raw: str | None) -> str:
    """Normalizes Schema.org availability URLs/strings to standard enum."""
    if not raw:
        return "unknown"
    val = raw.lower()
    if "instock" in val or "in_stock" in val:
        return "in_stock"
    if "outofstock" in val or "out_of_stock" in val or "soldout" in val:
        return "out_of_stock"
    if "preorder" in val or "backorder" in val:
        return "preorder"
    return "unknown"


def normalize_condition(raw: str | None) -> str:
    """Normalizes Schema.org itemCondition to standard enum (new, refurbished, used)."""
    if not raw:
        return "new"
    val = raw.lower()
    if "refurbished" in val or "renewed" in val:
        return "refurbished"
    if "used" in val or "preowned" in val:
        return "used"
    return "new"


def parse_price(val: Any) -> Decimal | None:
    """Parses numeric price string into quantized Decimal."""
    if val is None:
        return None
    cleaned = re.sub(r"[^\d.]", "", str(val).strip())
    if not cleaned:
        return None
    try:
        return Decimal(cleaned).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError):
        return None


class StructuredExtractor:
    """Extracts and normalizes product and offer data from HTML."""

    def extract(self, html: str, base_url: str = "") -> ExtractedProduct | None:
        if not html or not html.strip():
            return None

        # 1. Extract JSON-LD and microdata using extruct
        try:
            data = extruct.extract(html, base_url=base_url, uniform=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("extruct failed to parse HTML: %s", exc)
            data = {}

        json_ld_items = data.get("json-ld") or []

        # Find Product nodes (flattening any @graph structures)
        product_node = self._find_product_node(json_ld_items)

        # If extruct did not find product node or failed on malformed scripts, try lenient BS4 extraction
        if not product_node:
            lenient_items = self._extract_jsonld_lenient(html)
            product_node = self._find_product_node(lenient_items)

        if product_node:
            extracted = self._parse_jsonld_product(product_node)
            if extracted:
                return extracted

        # 2. Check microdata if JSON-LD did not yield a product
        microdata_items = data.get("microdata") or []
        product_node = self._find_product_node(microdata_items)
        if product_node:
            extracted = self._parse_jsonld_product(product_node)
            if extracted:
                return extracted

        # 3. Fallback: Parse OpenGraph / standard HTML meta tags via BeautifulSoup
        return self._parse_opengraph_fallback(html)

    def _extract_jsonld_lenient(self, html: str) -> list[dict[str, Any]]:
        """Resiliently parses <script type="application/ld+json"> directly with BS4."""
        import json

        soup = BeautifulSoup(html, "html.parser")
        items: list[dict[str, Any]] = []
        for s in soup.find_all("script", type="application/ld+json"):
            raw = (s.string or s.text or "").strip()
            if not raw:
                continue
            # Attempt 1: Direct lenient json load
            try:
                parsed = json.loads(raw, strict=False)
                if isinstance(parsed, list):
                    items.extend([p for p in parsed if isinstance(p, dict)])
                elif isinstance(parsed, dict):
                    items.append(parsed)
                continue
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                logger.debug("Lenient JSON-LD parse attempt 1 failed: %s", exc)

            # Attempt 2: Clean trailing duplicate braces (e.g. Croma bug: '}}')
            cleaned = re.sub(r"\}\s*\}\s*$", "}", raw)
            try:
                parsed = json.loads(cleaned, strict=False)
                if isinstance(parsed, list):
                    items.extend([p for p in parsed if isinstance(p, dict)])
                elif isinstance(parsed, dict):
                    items.append(parsed)
                continue
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                logger.debug("Lenient JSON-LD parse attempt 2 failed: %s", exc)
        return items

    def _find_product_node(self, items: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Recursively finds a schema.org Product or ProductModel node."""
        for item in items:
            if not isinstance(item, dict):
                continue

            # Check if this item is in an @graph list
            if "@graph" in item and isinstance(item["@graph"], list):
                found = self._find_product_node(item["@graph"])
                if found:
                    return found

            item_type = item.get("@type")
            if isinstance(item_type, list):
                types = [t.lower() for t in item_type if isinstance(t, str)]
            elif isinstance(item_type, str):
                types = [item_type.lower()]
            else:
                types = []

            if any(t in ("product", "individualproduct", "productmodel") for t in types):
                return item

        return None

    def _parse_jsonld_product(self, node: dict[str, Any]) -> ExtractedProduct | None:
        title = node.get("name") or node.get("title")
        if not title:
            return None

        # Extract Brand
        brand_val = node.get("brand")
        brand = None
        if isinstance(brand_val, dict):
            brand = brand_val.get("name")
        elif isinstance(brand_val, str):
            brand = brand_val

        # Extract GTIN / EAN / UPC
        gtin = (
            node.get("gtin13")
            or node.get("gtin14")
            or node.get("gtin12")
            or node.get("gtin8")
            or node.get("gtin")
            or node.get("isbn")
        )
        gtin = normalize_gtin(gtin)

        # Extract Model, MPN, SKU
        model = node.get("model")
        if isinstance(model, dict):
            model = model.get("name")

        mpn = node.get("mpn")
        sku = node.get("sku")
        description = node.get("description")
        image = node.get("image")
        if isinstance(image, list) and image:
            image = image[0]
        if isinstance(image, dict):
            image = image.get("url")

        # Parse Offers
        offers_data = node.get("offers")
        extracted_offers: list[ExtractedOffer] = []

        if isinstance(offers_data, dict):
            extracted_offers.extend(self._parse_offers_dict(offers_data))
        elif isinstance(offers_data, list):
            for off in offers_data:
                if isinstance(off, dict):
                    extracted_offers.extend(self._parse_offers_dict(off))

        primary_offer = extracted_offers[0] if extracted_offers else None

        return ExtractedProduct(
            title=str(title).strip(),
            brand=str(brand).strip() if brand else None,
            model=str(model).strip() if model else None,
            gtin=gtin,
            mpn=str(mpn).strip() if mpn else None,
            sku=str(sku).strip() if sku else None,
            description=str(description).strip() if description else None,
            image_url=str(image) if image else None,
            primary_offer=primary_offer,
            all_offers=extracted_offers,
            raw_specs=node,
        )

    def _parse_offers_dict(self, offer_dict: dict[str, Any]) -> list[ExtractedOffer]:
        """Handles single Offer or AggregateOffer structures."""
        results: list[ExtractedOffer] = []

        offer_type = str(offer_dict.get("@type", "")).lower()

        # Handle AggregateOffer with nested offers
        if "aggregateoffer" in offer_type and "offers" in offer_dict:
            nested = offer_dict["offers"]
            if isinstance(nested, list):
                for item in nested:
                    if isinstance(item, dict):
                        results.extend(self._parse_single_offer(item))
                if results:
                    return results

        # Single offer parsing (or top-level aggregate offer price)
        results.extend(self._parse_single_offer(offer_dict))
        return results

    def _parse_single_offer(self, offer: dict[str, Any]) -> list[ExtractedOffer]:
        currency = offer.get("priceCurrency") or "USD"
        raw_price = offer.get("price") or offer.get("lowPrice")
        price = parse_price(raw_price)

        availability = normalize_availability(offer.get("availability"))
        condition = normalize_condition(offer.get("itemCondition"))

        seller = offer.get("seller")
        if isinstance(seller, dict):
            seller = seller.get("name")

        if price is None and availability == "unknown":
            return []

        return [
            ExtractedOffer(
                currency=currency.strip().upper(),
                base_price=price,
                total_price=price,  # If fees/taxes are unspecified
                availability=availability,
                condition=condition,
                seller=str(seller).strip() if seller else None,
                price_status="ok" if price is not None else "unavailable",
                raw_data=offer,
            )
        ]

    def _parse_opengraph_fallback(self, html: str) -> ExtractedProduct | None:
        """Fallback to OpenGraph meta tags."""
        soup = BeautifulSoup(html, "html.parser")

        title_tag = soup.find("meta", property="og:title") or soup.find("title")
        if not title_tag:
            return None

        title = title_tag.get("content") if title_tag.name == "meta" else title_tag.text
        if not title or not title.strip():
            return None

        # Price & Currency
        price_tag = soup.find("meta", property="product:price:amount") or soup.find(
            "meta", property="og:price:amount"
        )
        curr_tag = soup.find("meta", property="product:price:currency") or soup.find(
            "meta", property="og:price:currency"
        )

        price = parse_price(price_tag.get("content")) if price_tag else None
        currency = (curr_tag.get("content") or "USD").upper() if curr_tag else "USD"

        # Image
        img_tag = soup.find("meta", property="og:image")
        image_url = img_tag.get("content") if img_tag else None

        # Description
        desc_tag = soup.find("meta", property="og:description")
        description = desc_tag.get("content") if desc_tag else None

        primary_offer = None
        if price is not None:
            primary_offer = ExtractedOffer(
                currency=currency,
                base_price=price,
                total_price=price,
                availability="in_stock",
                condition="new",
                price_status="ok",
            )

        return ExtractedProduct(
            title=title.strip(),
            image_url=image_url,
            description=description,
            primary_offer=primary_offer,
            all_offers=[primary_offer] if primary_offer else [],
        )


extractor = StructuredExtractor()
