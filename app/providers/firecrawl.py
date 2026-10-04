"""Firecrawl rare emergency fallback scraper with strict credit caps."""

import logging

import httpx

from app.config import settings
from app.providers.base import FetchResult

logger = logging.getLogger(__name__)


class FirecrawlCreditCapExceededError(Exception):
    """Raised when Firecrawl credit quota limit has been exhausted."""


class FirecrawlClient:
    """Client for Firecrawl API with hard credit usage caps and fallback guarding."""

    API_BASE = "https://api.firecrawl.dev/v1/scrape"

    def __init__(self, api_key: str | None = None) -> None:
        if api_key is not None:
            self._api_key = api_key
        else:
            self._api_key = settings.FIRECRAWL_API_KEY
        self._credits_used = 0

    @property
    def credits_used(self) -> int:
        return self._credits_used

    @property
    def remaining_credits(self) -> int:
        return max(0, settings.FIRECRAWL_MAX_CREDITS - self._credits_used)

    def has_available_credits(self) -> bool:
        return bool(self._api_key) and (self._credits_used < settings.FIRECRAWL_MAX_CREDITS)

    async def scrape(self, url: str) -> FetchResult:
        """Executes a rare fallback scrape only if credentials and credits exist."""
        if not self._api_key:
            return FetchResult(
                url=url,
                status_code=400,
                content="",
                content_type="",
                is_success=False,
                error_message="Firecrawl API key is not configured.",
                used_fallback=True,
            )

        if not self.has_available_credits():
            logger.warning(
                "Firecrawl scrape refused: hard credit cap reached (%d / %d credits used).",
                self._credits_used,
                settings.FIRECRAWL_MAX_CREDITS,
            )
            return FetchResult(
                url=url,
                status_code=429,
                content="",
                content_type="",
                is_success=False,
                error_message=f"Firecrawl free-tier credit cap reached ({settings.FIRECRAWL_MAX_CREDITS} credits).",
                used_fallback=True,
            )

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "url": url,
            "formats": ["html"],
            "onlyMainContent": False,
        }

        try:
            async with httpx.AsyncClient(
                timeout=float(settings.FETCH_TIMEOUT_SECONDS * 2)
            ) as client:
                resp = await client.post(self.API_BASE, json=payload, headers=headers)
                self._credits_used += 1

                if resp.status_code != 200:
                    return FetchResult(
                        url=url,
                        status_code=resp.status_code,
                        content="",
                        content_type="",
                        is_success=False,
                        error_message=f"Firecrawl API error: {resp.status_code} - {resp.text[:200]}",
                        used_fallback=True,
                    )

                data = resp.json()
                html_content = (data.get("data") or {}).get("html", "")
                return FetchResult(
                    url=url,
                    status_code=200,
                    content=html_content,
                    content_type="text/html",
                    is_success=True,
                    used_fallback=True,
                )

        except Exception as exc:  # noqa: BLE001
            return FetchResult(
                url=url,
                status_code=500,
                content="",
                content_type="",
                is_success=False,
                error_message=f"Firecrawl fallback error: {exc!s}",
                used_fallback=True,
            )


firecrawl_client = FirecrawlClient()
