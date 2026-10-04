"""Market and currency detection from domain names and structured page signals."""

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class MarketInfo:
    """Detected market country, currency, and resolution confidence."""

    country: str | None  # ISO 3166-1 alpha-2, e.g. "IN", "US", "GB", "DE", "CA"
    currency: str | None  # ISO 4217, e.g. "INR", "USD", "GBP", "EUR", "CAD"
    confidence: str  # "high", "medium", "needs_input"
    clarification_prompt: str | None = None


# Known domain mappings
DOMAIN_MARKET_MAP: dict[str, tuple[str, str]] = {
    # India
    "amazon.in": ("IN", "INR"),
    "flipkart.com": ("IN", "INR"),
    "croma.com": ("IN", "INR"),
    "reliancedigital.in": ("IN", "INR"),
    "tatacliq.com": ("IN", "INR"),
    # United States
    "amazon.com": ("US", "USD"),
    "bestbuy.com": ("US", "USD"),
    "walmart.com": ("US", "USD"),
    "target.com": ("US", "USD"),
    "bhphotovideo.com": ("US", "USD"),
    "newegg.com": ("US", "USD"),
    # United Kingdom
    "amazon.co.uk": ("GB", "GBP"),
    "currys.co.uk": ("GB", "GBP"),
    "argos.co.uk": ("GB", "GBP"),
    "johnlewis.com": ("GB", "GBP"),
    # Germany / EU
    "amazon.de": ("DE", "EUR"),
    "mediamarkt.de": ("DE", "EUR"),
    "saturn.de": ("DE", "EUR"),
    "otto.de": ("DE", "EUR"),
    # Canada
    "amazon.ca": ("CA", "CAD"),
    "bestbuy.ca": ("CA", "CAD"),
}

# Country code top-level domains (ccTLDs)
CCTLD_MAP: dict[str, tuple[str, str]] = {
    "in": ("IN", "INR"),
    "uk": ("GB", "GBP"),
    "co.uk": ("GB", "GBP"),
    "de": ("DE", "EUR"),
    "ca": ("CA", "CAD"),
    "fr": ("FR", "EUR"),
    "it": ("IT", "EUR"),
    "es": ("ES", "EUR"),
    "au": ("AU", "AUD"),
    "jp": ("JP", "JPY"),
}


def detect_market_from_domain(url_or_domain: str) -> MarketInfo:
    """Detects country and currency from a URL host or domain name."""
    if not url_or_domain:
        return MarketInfo(
            country=None,
            currency=None,
            confidence="needs_input",
            clarification_prompt="Which country should I search in?",
        )

    # Extract hostname
    if "://" in url_or_domain:
        parsed = urlparse(url_or_domain)
        hostname = (parsed.hostname or "").lower()
    else:
        # Strip path if passed e.g. "amazon.in/dp/..."
        hostname = url_or_domain.split("/")[0].lower()

    hostname = hostname.removeprefix("www.")

    # 1. Exact domain check
    if hostname in DOMAIN_MARKET_MAP:
        country, currency = DOMAIN_MARKET_MAP[hostname]
        return MarketInfo(country=country, currency=currency, confidence="high")

    # 2. Check suffix / ccTLD
    parts = hostname.split(".")
    if len(parts) >= 2:
        # Check two-part TLD first, e.g. co.uk
        if len(parts) >= 3:
            two_part_tld = f"{parts[-2]}.{parts[-1]}"
            if two_part_tld in CCTLD_MAP:
                country, currency = CCTLD_MAP[two_part_tld]
                return MarketInfo(country=country, currency=currency, confidence="high")

        tld = parts[-1]
        if tld in CCTLD_MAP:
            country, currency = CCTLD_MAP[tld]
            return MarketInfo(country=country, currency=currency, confidence="high")

    # 3. .com generic domain without specific mapping
    if hostname.endswith(".com"):
        # Most .com stores without regional TLD default to US / USD, but confidence is medium
        return MarketInfo(
            country="US",
            currency="USD",
            confidence="medium",
        )

    # Unclear - ask user rather than guessing or inferring location
    return MarketInfo(
        country=None,
        currency=None,
        confidence="needs_input",
        clarification_prompt="Which country should I search in?",
    )


def reconcile_market(domain_market: MarketInfo, page_currency: str | None) -> MarketInfo:
    """Cross-checks domain market against structured page data (JSON-LD priceCurrency)."""
    if not page_currency:
        return domain_market

    clean_page_curr = page_currency.strip().upper()

    # If domain market has currency and it agrees, high confidence
    if domain_market.currency and domain_market.currency == clean_page_curr:
        return MarketInfo(
            country=domain_market.country,
            currency=clean_page_curr,
            confidence="high",
        )

    # If page currency is specified but differs from domain currency, page currency takes priority
    # for the offer currency, but market may need verification
    if domain_market.currency and domain_market.currency != clean_page_curr:
        return MarketInfo(
            country=domain_market.country,
            currency=clean_page_curr,
            confidence="medium",
        )

    return MarketInfo(
        country=domain_market.country,
        currency=clean_page_curr,
        confidence="high" if domain_market.country else "medium",
    )
