"""SSRF-safe asynchronous HTTP fetcher with domain rate limiting."""

import asyncio
import ipaddress
import logging
import socket
import time
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.providers.base import FetchResult

logger = logging.getLogger(__name__)

# Max response size: 5 Megabytes
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 3
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 (DealWatch/1.0)"
)


class SSRFValidationError(ValueError):
    """Raised when a URL targets a private, loopback, or cloud metadata address."""


class SafeFetcher:
    """SSRF-hardened async HTTP fetcher with per-domain rate limiting."""

    def __init__(self) -> None:
        self._last_request_time: dict[str, float] = {}
        self._rate_lock = asyncio.Lock()

    def validate_url_security(self, url: str) -> None:
        """Validates that a URL is HTTPS and resolves exclusively to safe public IP addresses."""
        if not url or not isinstance(url, str):
            raise SSRFValidationError("URL must be a non-empty string.")

        parsed = urlparse(url)
        if parsed.scheme.lower() != "https":
            raise SSRFValidationError(
                f"Insecure scheme '{parsed.scheme}'. Only HTTPS is permitted."
            )

        hostname = parsed.hostname
        if not hostname:
            raise SSRFValidationError("URL is missing a valid hostname.")

        # Check for numeric or bracketed IP addresses in hostname
        clean_host = hostname.strip("[]")
        try:
            ip = ipaddress.ip_address(clean_host)
            self._check_ip_safety(ip)
            return
        except ValueError:
            # Hostname is a domain name, proceed to DNS resolution
            pass

        # Resolve hostname via DNS
        try:
            addr_info = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise SSRFValidationError(
                f"DNS resolution failed for hostname '{hostname}': {exc!s}"
            ) from exc

        if not addr_info:
            raise SSRFValidationError(f"No IP addresses resolved for hostname '{hostname}'.")

        for entry in addr_info:
            sockaddr = entry[4]
            ip_str = sockaddr[0]
            ip = ipaddress.ip_address(ip_str)
            self._check_ip_safety(ip)

    @staticmethod
    def _check_ip_safety(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
        """Enforces that an IP address is strictly a routable public address."""
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise SSRFValidationError(
                f"Blocked access to non-public/restricted IP address: {ip} (private/loopback/metadata)"
            )

        # Explicit check for Cloud Metadata service IPv4 (169.254.169.254)
        if str(ip) == "169.254.169.254":
            raise SSRFValidationError(
                "Access to cloud metadata service (169.254.169.254) is forbidden."
            )

    async def _enforce_rate_limit(self, domain: str) -> None:
        """Ensures per-domain minimum delay between requests."""
        min_delay = settings.PER_DOMAIN_MIN_DELAY_SECONDS
        async with self._rate_lock:
            now = time.monotonic()
            last_time = self._last_request_time.get(domain, 0.0)
            elapsed = now - last_time
            if elapsed < min_delay:
                await asyncio.sleep(min_delay - elapsed)
            self._last_request_time[domain] = time.monotonic()

    async def fetch(self, url: str) -> FetchResult:
        """Performs a secure GET request, validating redirects and enforcing size limits."""
        current_url = url
        redirect_count = 0

        async with httpx.AsyncClient(
            timeout=float(settings.FETCH_TIMEOUT_SECONDS),
            headers={"User-Agent": DEFAULT_USER_AGENT},
            follow_redirects=False,
        ) as client:
            while redirect_count <= MAX_REDIRECTS:
                # 1. SSRF Validation before every hop
                try:
                    self.validate_url_security(current_url)
                except SSRFValidationError as err:
                    logger.warning("SSRF check blocked URL: %s (%s)", current_url, err)
                    return FetchResult(
                        url=current_url,
                        status_code=400,
                        content="",
                        content_type="",
                        is_success=False,
                        error_message=f"SSRF validation blocked request: {err!s}",
                    )

                # 2. Per-domain rate limit
                parsed = urlparse(current_url)
                domain = (parsed.hostname or "").lower()
                await self._enforce_rate_limit(domain)

                # 3. Execute HTTP request
                try:
                    response = await client.get(current_url)
                except httpx.TimeoutException as exc:
                    return FetchResult(
                        url=current_url,
                        status_code=408,
                        content="",
                        content_type="",
                        is_success=False,
                        error_message=f"Request timed out after {settings.FETCH_TIMEOUT_SECONDS}s: {exc!s}",
                    )
                except httpx.HTTPError as exc:
                    return FetchResult(
                        url=current_url,
                        status_code=500,
                        content="",
                        content_type="",
                        is_success=False,
                        error_message=f"HTTP connection error: {exc!s}",
                    )

                # 4. Handle redirects manually to enforce SSRF validation on the destination
                if response.is_redirect:
                    location = response.headers.get("Location")
                    if not location:
                        break
                    # Normalize relative redirect paths
                    if location.startswith("/"):
                        location = f"{parsed.scheme}://{parsed.netloc}{location}"
                    current_url = location
                    redirect_count += 1
                    continue

                # 5. Check response size limit
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > MAX_RESPONSE_BYTES:
                    return FetchResult(
                        url=current_url,
                        status_code=413,
                        content="",
                        content_type=response.headers.get("Content-Type", ""),
                        is_success=False,
                        error_message=f"Response exceeded size cap of {MAX_RESPONSE_BYTES} bytes.",
                    )

                body = response.text
                if len(body.encode("utf-8")) > MAX_RESPONSE_BYTES:
                    return FetchResult(
                        url=current_url,
                        status_code=413,
                        content="",
                        content_type=response.headers.get("Content-Type", ""),
                        is_success=False,
                        error_message="Response text exceeded size cap.",
                    )

                content_type = response.headers.get("Content-Type", "")
                is_success = 200 <= response.status_code < 300
                return FetchResult(
                    url=current_url,
                    status_code=response.status_code,
                    content=body,
                    content_type=content_type,
                    is_success=is_success,
                    error_message=None if is_success else f"HTTP status {response.status_code}",
                )

            return FetchResult(
                url=current_url,
                status_code=310,
                content="",
                content_type="",
                is_success=False,
                error_message=f"Exceeded maximum redirect limit of {MAX_REDIRECTS}.",
            )


fetcher = SafeFetcher()
