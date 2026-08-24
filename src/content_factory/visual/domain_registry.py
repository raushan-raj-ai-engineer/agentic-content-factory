from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DomainProfile:
    name: str
    family: str
    high: tuple[str, ...]
    medium: tuple[str, ...]
    negative: tuple[str, ...]


@dataclass(frozen=True)
class DomainClassification:
    domain: str
    family: str
    score: float
    confidence: float
    secondary_domain: str | None
    secondary_score: float
    hits: tuple[str, ...]
    ambiguous: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "family": self.family,
            "score": round(self.score, 2),
            "confidence": round(self.confidence, 3),
            "secondary_domain": self.secondary_domain,
            "secondary_score": round(self.secondary_score, 2),
            "hits": list(self.hits),
            "ambiguous": self.ambiguous,
        }


DEFAULT_FAMILY = "factual_editorial"


def _registry_path() -> Path:
    # project_root/configs/domains.json
    return Path(__file__).resolve().parents[3] / "configs" / "domains.json"


@lru_cache(maxsize=1)
def load_registry() -> dict[str, Any]:
    path = _registry_path()

    if not path.is_file():
        raise RuntimeError(
            f"Domain registry missing: {path}"
        )

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


@lru_cache(maxsize=64)
def get_domain_profile(
    name: str,
) -> DomainProfile:
    registry = load_registry()

    for item in registry["domains"]:
        if item["name"] == name:
            return DomainProfile(
                name=item["name"],
                family=item["family"],
                high=tuple(item.get("high", [])),
                medium=tuple(item.get("medium", [])),
                negative=tuple(item.get("negative", [])),
            )

    return DomainProfile(
        name="general",
        family=DEFAULT_FAMILY,
        high=(),
        medium=(),
        negative=(),
    )


def domain_family(
    name: str,
) -> str:
    return get_domain_profile(
        name
    ).family


def classify_domain(
    text: str,
    visual_type: str = "",
) -> DomainClassification:
    registry = load_registry()

    value = _normalize(
        text
    )
    vtype = _normalize(
        visual_type
    )

    scored: list[
        tuple[
            float,
            str,
            str,
            tuple[str, ...],
        ]
    ] = []

    for item in registry["domains"]:
        name = item["name"]
        family = item["family"]

        score = 0.0
        hits: list[str] = []

        # Explicit visual type is strong evidence.
        if name.replace("_", " ") in vtype:
            score += 12.0
            hits.append(
                f"visual_type:{name}"
            )

        for marker in item.get(
            "high",
            [],
        ):
            if _contains(
                value,
                marker,
            ):
                # Longer phrases carry more discriminative signal.
                bonus = min(
                    2.0,
                    max(
                        0.0,
                        (
                            len(
                                marker.strip()
                            )
                            - 5
                        )
                        / 16.0,
                    ),
                )
                score += 7.0 + bonus
                hits.append(
                    f"high:{marker}"
                )

        for marker in item.get(
            "medium",
            [],
        ):
            if _contains(
                value,
                marker,
            ):
                score += 3.0
                hits.append(
                    f"medium:{marker}"
                )

        for marker in item.get(
            "negative",
            [],
        ):
            if _contains(
                value,
                marker,
            ):
                score -= 8.0
                hits.append(
                    f"negative:{marker}"
                )

        # Avoid a domain winning from one weak generic word.
        if score > 0:
            scored.append(
                (
                    score,
                    name,
                    family,
                    tuple(
                        hits[
                            :12
                        ]
                    ),
                )
            )

    if not scored:
        return DomainClassification(
            domain="general",
            family=DEFAULT_FAMILY,
            score=0.0,
            confidence=0.0,
            secondary_domain=None,
            secondary_score=0.0,
            hits=(),
            ambiguous=False,
        )

    scored.sort(
        reverse=True,
        key=lambda item: item[0],
    )

    best = scored[0]
    second = (
        scored[1]
        if len(
            scored
        ) > 1
        else (
            0.0,
            None,
            None,
            (),
        )
    )

    min_score = float(
        registry.get(
            "min_score",
            5.0,
        )
    )
    margin = float(
        registry.get(
            "ambiguity_margin",
            1.5,
        )
    )

    best_score = best[0]
    second_score = float(
        second[0]
        or 0.0
    )

    ambiguous = (
        best_score
        >= min_score
        and second_score
        >= min_score
        and (
            best_score
            - second_score
        )
        < margin
        and best[2]
        != second[2]
    )

    if best_score < min_score:
        return DomainClassification(
            domain="general",
            family=DEFAULT_FAMILY,
            score=best_score,
            confidence=_confidence(
                best_score,
                second_score,
            ),
            secondary_domain=(
                second[1]
                if second[1]
                else None
            ),
            secondary_score=second_score,
            hits=best[3],
            ambiguous=True,
        )

    # If the result is genuinely close between unrelated visual families,
    # prefer safe general factual routing over a confident wrong domain.
    if ambiguous and best_score < 12.0:
        return DomainClassification(
            domain="general",
            family=DEFAULT_FAMILY,
            score=best_score,
            confidence=_confidence(
                best_score,
                second_score,
            ),
            secondary_domain=(
                best[1]
            ),
            secondary_score=best_score,
            hits=best[3],
            ambiguous=True,
        )

    return DomainClassification(
        domain=best[1],
        family=best[2],
        score=best_score,
        confidence=_confidence(
            best_score,
            second_score,
        ),
        secondary_domain=(
            second[1]
            if second[1]
            else None
        ),
        secondary_score=second_score,
        hits=best[3],
        ambiguous=ambiguous,
    )


def prefers_public_media(
    domain: str,
) -> bool:
    return domain_family(
        domain
    ) in {
        "factual_real_media",
        "lifestyle_real_media",
    }


def _confidence(
    best: float,
    second: float,
) -> float:
    if best <= 0:
        return 0.0

    strength = 1.0 - math.exp(
        -best
        / 10.0
    )
    separation = (
        max(
            0.0,
            best
            - second,
        )
        / max(
            1.0,
            best,
        )
    )

    return min(
        0.99,
        max(
            0.0,
            (
                strength
                * 0.72
            )
            + (
                separation
                * 0.28
            ),
        ),
    )


def _normalize(
    text: str,
) -> str:
    value = (
        text
        or ""
    ).lower()

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return (
        " "
        + value.strip()
        + " "
    )


def _contains(
    text: str,
    marker: str,
) -> bool:
    marker_norm = (
        marker
        or ""
    ).lower()

    if not marker_norm:
        return False

    # Markers that intentionally contain spaces use phrase matching.
    if (
        marker_norm.startswith(
            " "
        )
        or marker_norm.endswith(
            " "
        )
        or " "
        in marker_norm.strip()
        or any(
            ord(char) > 127
            for char in marker_norm
        )
    ):
        return marker_norm.strip() in text

    # ASCII single-word markers use token boundaries to prevent cases such as
    # "car" matching "career" and "law" matching "flaw".
    return re.search(
        rf"(?<![a-z0-9]){re.escape(marker_norm)}(?![a-z0-9])",
        text,
    ) is not None
