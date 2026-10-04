"""Exact matching hierarchy and product compatibility verification."""

import re
from typing import Any

from app.verticals.base import MatchResult

# Accessory indicator keywords that differentiate accessories from main products
ACCESSORY_KEYWORDS = {
    "case",
    "cover",
    "screen protector",
    "tempered glass",
    "cable",
    "charger",
    "adapter",
    "strap",
    "band",
    "holder",
    "mount",
    "skin",
    "pouch",
}

# Quantity / pack patterns e.g. "pack of 2", "2-pack", "set of 3"
PACK_PATTERN = re.compile(r"\b(?:pack of|set of)\s*(\d+)\b|\b(\d+)\s*pack\b", re.IGNORECASE)

# Storage capacity regex: e.g. 64gb, 128gb, 256gb, 512gb, 1tb
STORAGE_PATTERN = re.compile(r"\b(\d+)\s*(gb|tb)\b", re.IGNORECASE)


def normalize_gtin(gtin: str | None) -> str | None:
    """Normalizes GTIN/EAN/UPC by stripping non-numeric characters and validating length."""
    if not gtin:
        return None
    digits = re.sub(r"\D", "", str(gtin))
    # Standard GTIN lengths: GTIN-8, GTIN-12 (UPC), GTIN-13 (EAN), GTIN-14
    if len(digits) in (8, 12, 13, 14):
        return digits
    return None


def extract_pack_quantity(text: str) -> int:
    """Detects multi-pack quantity, default 1."""
    if not text:
        return 1
    match = PACK_PATTERN.search(text)
    if match:
        qty_str = match.group(1) or match.group(2)
        try:
            return int(qty_str)
        except ValueError:
            return 1
    return 1


def is_accessory_mismatch(subject_title: str, candidate_title: str) -> bool:
    """Detects if candidate title is an accessory while subject is a primary device (or vice versa)."""
    subj_lower = subject_title.lower()
    cand_lower = candidate_title.lower()

    subj_has_accessory = any(
        re.search(rf"\b{re.escape(w)}\b", subj_lower) for w in ACCESSORY_KEYWORDS
    )
    cand_has_accessory = any(
        re.search(rf"\b{re.escape(w)}\b", cand_lower) for w in ACCESSORY_KEYWORDS
    )

    # If one is an accessory and the other isn't, it's a mismatch
    return subj_has_accessory != cand_has_accessory


def extract_storage(text: str) -> str | None:
    """Extracts storage specification e.g. '128gb'."""
    if not text:
        return None
    matches = STORAGE_PATTERN.findall(text)
    if matches:
        # e.g. ('128', 'gb') -> '128gb'
        return f"{matches[0][0].lower()}{matches[0][1].lower()}"
    return None


def match_product(
    subject_details: dict[str, Any],
    candidate_offer: dict[str, Any],
) -> MatchResult:
    """Evaluates candidate offer against subject details following the strict hierarchy.

    Hierarchy:
    1. GTIN/EAN/UPC exact match
    2. MPN (Manufacturer Part Number) + Brand
    3. Brand + Model + Variant (storage, RAM, color, condition)
    4. Guard checks (accessory vs device, refurbished vs new, multi-pack)
    """
    reasons: list[str] = []

    # 1. Negative guard: Condition mismatch
    subj_cond = (subject_details.get("condition") or "new").lower()
    cand_cond = (candidate_offer.get("condition") or "new").lower()
    if subj_cond != cand_cond:
        return MatchResult(
            status="mismatch",
            matched_on=None,
            reasons=[f"Condition mismatch: subject is '{subj_cond}', candidate is '{cand_cond}'"],
        )

    # 2. Negative guard: Accessory vs Device mismatch
    subj_title = subject_details.get("title", "")
    cand_title = candidate_offer.get("title", "")
    if is_accessory_mismatch(subj_title, cand_title):
        return MatchResult(
            status="mismatch",
            matched_on=None,
            reasons=["Accessory vs device mismatch detected between titles"],
        )

    # 3. Negative guard: Multi-pack / Quantity mismatch
    subj_qty = extract_pack_quantity(subj_title)
    cand_qty = extract_pack_quantity(cand_title)
    if subj_qty != cand_qty:
        return MatchResult(
            status="mismatch",
            matched_on=None,
            reasons=[f"Pack quantity mismatch: subject is {subj_qty}, candidate is {cand_qty}"],
        )

    # 4. Negative guard: Storage capacity mismatch (e.g. 128GB vs 256GB)
    subj_storage = extract_storage(subj_title) or subject_details.get("raw_specs", {}).get(
        "storage"
    )
    cand_storage = extract_storage(cand_title) or candidate_offer.get("attributes", {}).get(
        "storage"
    )
    if (
        subj_storage
        and cand_storage
        and str(subj_storage).lower().replace(" ", "") != str(cand_storage).lower().replace(" ", "")
    ):
        return MatchResult(
            status="mismatch",
            matched_on=None,
            reasons=[f"Storage capacity mismatch: '{subj_storage}' vs '{cand_storage}'"],
        )

    # Step 1 in hierarchy: GTIN / EAN / UPC Match
    subj_gtin = normalize_gtin(subject_details.get("gtin"))
    cand_gtin = normalize_gtin(candidate_offer.get("gtin"))
    if subj_gtin and cand_gtin:
        if subj_gtin == cand_gtin:
            return MatchResult(
                status="exact",
                matched_on="gtin",
                reasons=[f"Verified exact match on GTIN/EAN/UPC: {subj_gtin}"],
            )
        else:
            return MatchResult(
                status="mismatch",
                matched_on=None,
                reasons=[f"GTIN mismatch: {subj_gtin} != {cand_gtin}"],
            )

    # Step 2 in hierarchy: MPN + Brand Match
    subj_mpn = (subject_details.get("mpn") or "").strip().upper()
    cand_mpn = (candidate_offer.get("mpn") or "").strip().upper()
    subj_brand = (subject_details.get("brand") or "").strip().lower()
    cand_brand = (candidate_offer.get("brand") or "").strip().lower()

    if subj_mpn and cand_mpn and subj_brand and cand_brand:
        if subj_brand == cand_brand and subj_mpn == cand_mpn:
            return MatchResult(
                status="exact",
                matched_on="mpn",
                reasons=[f"Verified exact match on Brand '{subj_brand}' and MPN '{subj_mpn}'"],
            )
        elif subj_mpn != cand_mpn:
            return MatchResult(
                status="mismatch",
                matched_on=None,
                reasons=[f"MPN mismatch: {subj_mpn} != {cand_mpn}"],
            )

    # Step 3 in hierarchy: Brand + Model + Variant
    subj_model = (subject_details.get("model") or "").strip().lower()
    cand_model = (candidate_offer.get("model") or "").strip().lower()
    subj_variant = (subject_details.get("variant") or "").strip().lower()
    cand_variant = (candidate_offer.get("variant") or "").strip().lower()

    if subj_brand and cand_brand and subj_brand != cand_brand:
        return MatchResult(
            status="mismatch",
            matched_on=None,
            reasons=[f"Brand mismatch: '{subj_brand}' vs '{cand_brand}'"],
        )

    if (
        subj_brand
        and subj_model
        and cand_brand
        and cand_model
        and subj_brand == cand_brand
        and subj_model == cand_model
    ):
        if subj_variant and cand_variant:
            if subj_variant == cand_variant:
                return MatchResult(
                    status="exact",
                    matched_on="brand_model_variant",
                    reasons=[
                        f"Verified exact match on Brand/Model/Variant: {subj_brand} {subj_model} ({subj_variant})"
                    ],
                )
            else:
                return MatchResult(
                    status="mismatch",
                    matched_on=None,
                    reasons=[f"Variant mismatch: '{subj_variant}' vs '{cand_variant}'"],
                )
        elif not subj_variant and not cand_variant:
            return MatchResult(
                status="exact",
                matched_on="brand_model_variant",
                reasons=[f"Verified exact match on Brand/Model: {subj_brand} {subj_model}"],
            )

    # If critical signals are incomplete or inconclusive, NEVER assume exact
    reasons.append(
        "Insufficient deterministic identifiers (GTIN, MPN, or full model/variant) to confirm exact match."
    )
    return MatchResult(
        status="uncertain",
        matched_on=None,
        reasons=reasons,
    )


async def match_product_with_llm(
    subject_details: dict[str, Any],
    candidate_offer: dict[str, Any],
    llm: Any = None,
) -> MatchResult:
    """Evaluates product match using deterministic hierarchy first.

    If result is 'uncertain' and LLM provider is provided, invokes LLM borderline verification.
    """
    deterministic_result = match_product(subject_details, candidate_offer)
    if deterministic_result.status != "uncertain" or not llm:
        return deterministic_result

    if hasattr(llm, "verify_borderline_match"):
        return await llm.verify_borderline_match(subject_details, candidate_offer)

    return deterministic_result
