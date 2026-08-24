from __future__ import annotations

import re
from dataclasses import dataclass

from content_factory.visual.domain_registry import (
    classify_domain,
    domain_family,
)


@dataclass(frozen=True)
class VisualDecision:
    domain: str
    route: str
    reason: str


REAL_PHOTO_TYPES = {
    "real_photo",
    "person_photo",
    "place_photo",
    "public_photo_scene",
    "person_scene",
    "place_scene",
}

TECH_TYPES = {
    "code",
    "technical_code",
    "technical_diagram",
    "technical_workflow",
    "technical_architecture",
    "technical_dashboard",
    "workflow",
    "architecture",
    "dashboard",
}

CREATIVE_TYPES = {
    "cartoon",
    "cartoon_scene",
    "character_scene",
    "gaming_key_art",
    "gaming_scene",
    "photo_illustration",
}


STRUCTURED_EDITORIAL_TYPES = {
    "infographic",
    "editorial_summary",
    "timeline_scene",
    "comparison_scene",
    "news_graphic",
    "finance_graphic",
    "sports_timeline",
    "sports_fact_card",
    "legal_timeline",
    "legal_comparison",
    "legal_fact_card",
}


def decide_visual_route(
    *,
    title: str,
    description: str,
    prompt: str,
    visual_type: str,
    context_domain: str | None = None,
) -> VisualDecision:
    combined = " ".join(
        [
            title or "",
            description or "",
            prompt or "",
        ]
    )

    vtype = (
        visual_type
        or "cinematic_explainer"
    ).strip().lower()

    local = classify_domain(
        combined,
        vtype,
    )

    domain = (
        context_domain
        if context_domain
        and context_domain
        != "general"
        else local.domain
    )

    family = domain_family(
        domain
    )

    if vtype in REAL_PHOTO_TYPES:
        return VisualDecision(
            domain=domain,
            route="public_photo",
            reason="scene explicitly requests reusable real-world media",
        )

    if vtype in STRUCTURED_EDITORIAL_TYPES:
        if domain == "sports":
            route = "editorial_sports"
        elif domain == "legal":
            route = "editorial_legal"
        elif domain == "education":
            route = "editorial_education"
        elif domain in {
            "news",
            "politics",
            "crime_safety",
            "public_service",
        }:
            route = "editorial_news"
        elif family == "data_finance":
            route = "editorial_finance"
        else:
            route = "editorial"

        return VisualDecision(
            domain=domain,
            route=route,
            reason=(
                "explicit structured/explainer visual overrides "
                "domain-family default"
            ),
        )

    if (
        vtype in TECH_TYPES
        or family == "technical"
    ):
        return VisualDecision(
            domain=domain,
            route="technical",
            reason="technical visual family",
        )

    explicit_creative = (
        vtype in CREATIVE_TYPES
        or "cartoon" in vtype
        or "gaming" in vtype
    )

    if (
        explicit_creative
        or family == "creative"
    ):
        return VisualDecision(
            domain=domain,
            route="diffusion",
            reason="creative visual family",
        )

    if family == "product_cinematic":
        return VisualDecision(
            domain=domain,
            route="product",
            reason="product-cinematic visual family",
        )

    if family == "data_finance":
        return VisualDecision(
            domain=domain,
            route="editorial_finance",
            reason="data/finance visual family",
        )

    if domain == "sports":
        return VisualDecision(
            domain=domain,
            route="editorial_sports",
            reason="sports factual context",
        )

    if domain == "legal":
        return VisualDecision(
            domain=domain,
            route="editorial_legal",
            reason="legal factual context",
        )

    if domain == "education":
        return VisualDecision(
            domain=domain,
            route="editorial_education",
            reason="education/public-service factual context",
        )

    if domain in {
        "news",
        "politics",
        "crime_safety",
        "public_service",
    }:
        return VisualDecision(
            domain=domain,
            route="editorial_news",
            reason="current/public-affairs factual context",
        )

    # For other real-media/lifestyle domains the provider will try reusable
    # public media first and fall back to generic editorial composition.
    if family in {
        "factual_real_media",
        "lifestyle_real_media",
    }:
        return VisualDecision(
            domain=domain,
            route="editorial",
            reason=f"{family} visual family",
        )

    return VisualDecision(
        domain=domain,
        route="editorial",
        reason="safe general factual fallback",
    )


def detect_domain(
    text: str,
    visual_type: str = "",
) -> str:
    return classify_domain(
        text,
        visual_type,
    ).domain


def extract_matchup(
    *values: str,
) -> tuple[str, str] | None:
    text = " ".join(
        value
        for value in values
        if value
    )

    patterns = (
        r"([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÿ0-9 .&'’-]{1,38}?)\s+"
        r"(?:vs\.?|versus)\s+"
        r"([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÿ0-9 .&'’-]{1,38})",
        r"([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÿ0-9 .&'’-]{1,38}?)\s+"
        r"[-–]\s+"
        r"([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÿ0-9 .&'’-]{1,38})",
    )

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        left = _clean_name(
            match.group(1)
        )
        right = _clean_name(
            match.group(2)
        )

        if left and right:
            return left, right

    return None


def _clean_name(
    value: str,
) -> str:
    value = re.sub(
        r"\s+",
        " ",
        value,
    ).strip(
        " .,:;!?-–—"
    )

    value = re.sub(
        r"^(?:about|between|for|on|the match|match)\s+",
        "",
        value,
        flags=re.IGNORECASE,
    )

    return value[:42].strip()
