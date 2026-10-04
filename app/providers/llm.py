"""Groq LLM provider for fallback text extraction and borderline match verification."""

import hashlib
import json
import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.config import settings
from app.verticals.base import MatchResult

logger = logging.getLogger(__name__)


class LLMExtractedProduct(BaseModel):
    """Pydantic schema for product specifications extracted by LLM from messy page text."""

    title: str = Field(description="Full product title")
    brand: str | None = Field(default=None, description="Manufacturer brand name")
    model: str | None = Field(default=None, description="Specific product model name")
    variant: str | None = Field(
        default=None, description="Variant info e.g. storage capacity, color, or edition"
    )
    gtin: str | None = Field(
        default=None, description="UPC, EAN, or GTIN if explicitly present in text"
    )
    mpn: str | None = Field(
        default=None, description="Manufacturer part number if explicitly present"
    )
    price: Decimal | None = Field(default=None, description="Observed numeric price")
    currency: str | None = Field(default=None, description="ISO 4217 currency code e.g. INR, USD")
    availability: Literal["in_stock", "out_of_stock", "preorder", "unknown"] = "unknown"
    condition: Literal["new", "refurbished", "used"] = "new"


class LLMMatchVerification(BaseModel):
    """Pydantic schema for LLM borderline match verification."""

    is_exact_match: bool = Field(
        description="True ONLY if the two items are demonstrably identical"
    )
    confidence: Literal["exact", "uncertain", "mismatch"] = Field(
        description="Confidence level: exact (100% same item & variant), mismatch (different item/variant/condition), or uncertain"
    )
    matched_on: str | None = Field(default="llm_verified", description="Matched field or technique")
    reasons: list[str] = Field(
        default_factory=list, description="Specific factual reasons for verdict"
    )


class GroqLLMProvider:
    """Async Groq provider with usage caps, response caching, and strict schema validation."""

    API_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_daily_calls: int | None = None,
    ) -> None:
        self._api_key = api_key or settings.GROQ_API_KEY
        self._model = model or settings.GROQ_MODEL
        self._max_daily_calls = max_daily_calls or settings.LLM_MAX_CALLS_PER_DAY

        # Daily usage counter
        self._current_date: date = datetime.now(UTC).date()
        self._calls_today: int = 0

        # In-memory prompt cache
        self._cache: dict[str, Any] = {}

    @property
    def calls_today(self) -> int:
        self._check_date_reset()
        return self._calls_today

    @property
    def remaining_calls_today(self) -> int:
        self._check_date_reset()
        return max(0, self._max_daily_calls - self._calls_today)

    def _check_date_reset(self) -> None:
        today = datetime.now(UTC).date()
        if today > self._current_date:
            self._current_date = today
            self._calls_today = 0
            self._cache.clear()

    def has_quota(self) -> bool:
        self._check_date_reset()
        return bool(self._api_key) and (self._calls_today < self._max_daily_calls)

    def _make_cache_key(self, prompt: str) -> str:
        return hashlib.sha256(f"{self._model}:{prompt}".encode()).hexdigest()

    async def _call_api_with_retry(
        self,
        system_prompt: str,
        user_prompt: str,
        schema_class: type[BaseModel],
    ) -> BaseModel | None:
        """Invokes Groq with 1 automatic retry on JSON/validation failure.

        Falls back gracefully if quota is exhausted or retries fail.
        """
        if not self._api_key:
            logger.warning("Groq LLM call skipped: GROQ_API_KEY is not configured.")
            return None

        self._check_date_reset()
        if not self.has_quota():
            logger.warning(
                "Groq LLM quota exceeded: %d / %d calls used today. Degrading gracefully.",
                self._calls_today,
                self._max_daily_calls,
            )
            return None

        cache_key = self._make_cache_key(f"{system_prompt}\n{user_prompt}")
        if cache_key in self._cache:
            return self._cache[cache_key]

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        payload = {
            "model": self._model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }

        # Attempt up to 2 tries (1 original + 1 retry)
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(self.API_ENDPOINT, headers=headers, json=payload)
                    self._calls_today += 1

                    if resp.status_code != 200:
                        logger.warning("Groq API error (%d): %s", resp.status_code, resp.text[:200])
                        continue

                    data = resp.json()
                    raw_content = data["choices"][0]["message"]["content"]
                    parsed_json = json.loads(raw_content)

                    # Validate against Pydantic schema
                    validated = schema_class.model_validate(parsed_json)
                    self._cache[cache_key] = validated
                    return validated

            except (httpx.HTTPError, json.JSONDecodeError, ValidationError, KeyError) as exc:
                logger.warning("Groq LLM attempt %d failed: %s", attempt + 1, exc)
                if attempt == 0:
                    # Provide correction hint on retry
                    messages.append(
                        {
                            "role": "user",
                            "content": f"The previous response failed schema validation. Please output strictly valid JSON conforming exactly to the required schema: {exc!s}",
                        }
                    )
                    payload["messages"] = messages
                continue

        logger.error("Groq LLM failed after 2 attempts. Returning graceful fallback.")
        return None

    async def extract_product_from_text(
        self,
        page_text: str,
        page_title: str | None = None,
    ) -> LLMExtractedProduct | None:
        """Extracts product brand, model, variant, and specs from messy page text when JSON-LD is missing."""
        system_prompt = (
            "You are a precise e-commerce product extraction assistant. "
            "Extract the product brand, model, variant (e.g. storage, color, size), GTIN/EAN/UPC, MPN, "
            "price, currency, availability, and condition from the provided product page content. "
            "Do NOT invent or guess missing numbers or specs. If unknown, set them to null. "
            "Output strictly valid JSON with keys: title, brand, model, variant, gtin, mpn, price, currency, availability, condition."
        )

        snippet = page_text[:4000] if len(page_text) > 4000 else page_text
        user_prompt = f"Page Title: {page_title or 'Unknown'}\n\nContent:\n{snippet}"

        res = await self._call_api_with_retry(system_prompt, user_prompt, LLMExtractedProduct)
        if isinstance(res, LLMExtractedProduct):
            return res
        return None

    async def verify_borderline_match(
        self,
        subject: dict[str, Any],
        candidate: dict[str, Any],
    ) -> MatchResult:
        """Verifies borderline matches when deterministic rules are uncertain.

        Rules:
        - Conflicting storage, RAM, variant, condition, or accessory vs main product MUST be mismatch.
        - If ambiguous or lacking conclusive proof, MUST be uncertain.
        - Only marked exact when they are demonstrably the identical product and variant.
        """
        system_prompt = (
            "You are a strict e-commerce product deal verification expert. "
            "Your task is to determine whether Candidate Product is the EXACT same product and variant as Subject Product. "
            "CRITICAL RULES:\n"
            "1. If conditions differ (e.g. new vs refurbished/used), output 'mismatch'.\n"
            "2. If storage, memory, size, or critical variants differ (e.g. 128GB vs 256GB), output 'mismatch'.\n"
            "3. If one is an accessory (case, cover, charger) and the other is the device itself, output 'mismatch'.\n"
            "4. If there is not enough information to be 100% certain they are the exact same item, output 'uncertain'.\n"
            "5. Output 'exact' ONLY if you are confident they are the identical product, model, and specification.\n"
            "Output strictly valid JSON with keys: is_exact_match (bool), confidence ('exact', 'uncertain', 'mismatch'), "
            "matched_on ('llm_verified'), reasons (array of clear strings)."
        )

        user_prompt = (
            f"Subject Product:\n"
            f"- Title: {subject.get('title')}\n"
            f"- Brand: {subject.get('brand')}\n"
            f"- Model: {subject.get('model')}\n"
            f"- Variant: {subject.get('variant')}\n"
            f"- Specs: {subject.get('raw_specs')}\n\n"
            f"Candidate Product:\n"
            f"- Title: {candidate.get('title')}\n"
            f"- Brand: {candidate.get('brand')}\n"
            f"- Model: {candidate.get('model')}\n"
            f"- Variant: {candidate.get('variant')}\n"
            f"- Attributes: {candidate.get('attributes')}\n"
        )

        res = await self._call_api_with_retry(system_prompt, user_prompt, LLMMatchVerification)
        if isinstance(res, LLMMatchVerification):
            return MatchResult(
                status=res.confidence,
                matched_on=res.matched_on if res.is_exact_match else None,
                reasons=res.reasons,
            )

        # Fallback if LLM call failed or quota exceeded: strictly uncertain (never fake confidence)
        return MatchResult(
            status="uncertain",
            matched_on=None,
            reasons=["LLM verification was unable to confirm match (fallback to uncertain)."],
        )


llm_provider = GroqLLMProvider()
