"""URL Canonicalization and normalization for deterministic deduplication."""

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# Common tracking / session / affiliate query parameter prefixes and names to strip
STRIP_QUERY_PARAMS = {
    # Analytics / Marketing
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    # Ad platforms
    "gclid",
    "gclsrc",
    "dclid",
    "fbclid",
    "igshid",
    "msclkid",
    "twclid",
    "mc_cid",
    "mc_eid",
    # Amazon tracking / referral
    "ref",
    "ref_",
    "tag",
    "linkcode",
    "camp",
    "creative",
    "creativeasin",
    "ascsubtag",
    "th",
    "psc",
    "qid",
    "sr",
    "keywords",
    "sprefix",
    "crid",
    "sp_csd",
    # Flipkart tracking
    "affid",
    "affextid",
    "lid",
    "marketplace",
    "spotlighttagid",
    # Generic session / referral
    "session-id",
    "session-id-time",
    "source",
}

# Prefix matching for parameters like pf_rd_*, pd_rd_*, etc.
STRIP_PREFIXES = ("utm_", "pd_rd_", "pf_rd_", "ref_")

# Regex to extract Amazon ASIN
AMAZON_ASIN_REGEX = re.compile(r"/(?:dp|gp/product|d)/([A-Z0-9]{10})(?:/|\?|$)", re.IGNORECASE)

# Regex to extract Flipkart product ID (/p/itm...)
FLIPKART_PID_REGEX = re.compile(r"(/[^/]+/p/itm[a-zA-Z0-9]+)", re.IGNORECASE)


def canonicalize_url(url: str) -> str:
    """Canonicalizes a retailer product URL to a clean, deterministic, unique form.

    Strips affiliate tags, tracking parameters, fragments, session IDs, and reduces
    domain-specific paths (e.g., Amazon ASINs) to their minimal canonical representation.
    """
    if not url or not isinstance(url, str):
        raise ValueError("URL must be a non-empty string.")

    cleaned = url.strip()
    if not cleaned.startswith(("http://", "https://")):
        cleaned = "https://" + cleaned

    parsed = urlparse(cleaned)
    if not parsed.hostname:
        raise ValueError(f"Invalid URL hostname in: {url}")

    hostname = parsed.hostname.lower()
    hostname = hostname.removeprefix("www.")

    path = parsed.path

    # Amazon domain canonicalization -> https://amazon.<tld>/dp/<ASIN>
    if "amazon." in hostname:
        match = AMAZON_ASIN_REGEX.search(path)
        if match:
            asin = match.group(1).upper()
            return f"https://{hostname}/dp/{asin}"

    # Flipkart canonicalization -> https://flipkart.com/<slug>/p/<pid> (strip all queries)
    if "flipkart." in hostname:
        match = FLIPKART_PID_REGEX.search(path)
        if match:
            clean_path = match.group(1)
            return f"https://{hostname}{clean_path}"

    # General URL cleaning: strip tracking parameters
    query_params = []
    for k, v in parse_qsl(parsed.query, keep_blank_values=False):
        k_lower = k.lower()
        if k_lower in STRIP_QUERY_PARAMS:
            continue
        if any(k_lower.startswith(prefix) for prefix in STRIP_PREFIXES):
            continue
        query_params.append((k, v))

    # Deterministic query string: sort by key
    query_params.sort(key=lambda pair: pair[0])
    new_query = urlencode(query_params)

    # Standardize path: remove trailing slash unless it's just '/'
    normalized_path = path.rstrip("/") if len(path) > 1 else path
    if not normalized_path:
        normalized_path = "/"

    canonical = urlunparse(
        (
            "https",
            hostname,
            normalized_path,
            "",  # params
            new_query,
            "",  # fragment stripped
        )
    )
    return canonical
