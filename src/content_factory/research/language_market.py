from __future__ import annotations

import json
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any


def _config_path() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "configs"
        / "language_markets.json"
    )


@lru_cache(maxsize=1)
def load_language_market_config() -> dict[str, Any]:
    path = _config_path()

    if not path.is_file():
        raise RuntimeError(
            f"Language market config missing: {path}"
        )

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def language_profile(
    code: str,
) -> dict[str, Any]:
    config = load_language_market_config()

    normalized = (
        code
        or "en"
    ).strip().lower()

    for item in config["languages"]:
        if item["code"] == normalized:
            return dict(item)

    return {
        "code": normalized,
        "name": normalized.upper(),
        "priority_rank": 999,
        "priority_weight": 0.50,
    }


def market_profile(
    geo: str,
) -> dict[str, Any]:
    config = load_language_market_config()

    normalized = (
        geo
        or "US"
    ).strip().upper()

    for item in config["markets"]:
        if item["geo"] == normalized:
            return dict(item)

    return {
        "geo": normalized,
        "name": normalized,
        "default_language": "en",
        "latin_language": "en",
        "youtube_ad_reach_m": 0.0,
        "news_hl": "en-US",
        "news_ceid": f"{normalized}:en",
    }


def configured_markets(
    limit: int | None = None,
) -> list[dict[str, Any]]:
    markets = [
        dict(item)
        for item in load_language_market_config()[
            "markets"
        ]
    ]

    markets.sort(
        key=lambda item: float(
            item.get(
                "youtube_ad_reach_m",
                0.0,
            )
        ),
        reverse=True,
    )

    if limit is None:
        return markets

    return markets[
        :max(
            1,
            int(limit),
        )
    ]


def detect_language(
    text: str,
    *,
    geo: str,
) -> dict[str, Any]:
    """
    Script-first language inference for trend titles.

    The source market resolves ambiguous Latin/Arabic-script text:
    - India Latin -> English
    - Brazil Latin -> Portuguese
    - Mexico Latin -> Spanish
    - Indonesia Latin -> Indonesian
    - Pakistan Arabic script -> Urdu
    - Saudi Arabia Arabic script -> Arabic
    """
    market = market_profile(
        geo
    )

    counts = {
        "bn": 0,
        "gu": 0,
        "hi": 0,
        "pa": 0,
        "ta": 0,
        "te": 0,
        "kn": 0,
        "ml": 0,
        "ar": 0,
        "ja": 0,
        "latin": 0,
    }

    for char in text or "":
        code = ord(char)

        if 0x0980 <= code <= 0x09FF:
            counts["bn"] += 1
        elif 0x0A80 <= code <= 0x0AFF:
            counts["gu"] += 1
        elif 0x0900 <= code <= 0x097F:
            counts["hi"] += 1
        elif 0x0A00 <= code <= 0x0A7F:
            counts["pa"] += 1
        elif 0x0B80 <= code <= 0x0BFF:
            counts["ta"] += 1
        elif 0x0C00 <= code <= 0x0C7F:
            counts["te"] += 1
        elif 0x0C80 <= code <= 0x0CFF:
            counts["kn"] += 1
        elif 0x0D00 <= code <= 0x0D7F:
            counts["ml"] += 1
        elif (
            0x0600 <= code <= 0x06FF
            or 0x0750 <= code <= 0x077F
        ):
            counts["ar"] += 1
        elif (
            0x3040 <= code <= 0x30FF
            or 0x4E00 <= code <= 0x9FFF
        ):
            counts["ja"] += 1
        elif (
            "LATIN"
            in unicodedata.name(
                char,
                "",
            )
        ):
            counts["latin"] += 1

    script_code = max(
        counts,
        key=counts.get,
    )

    if counts[
        script_code
    ] == 0:
        language_code = market[
            "default_language"
        ]

    elif script_code == "latin":
        language_code = market.get(
            "latin_language",
            market[
                "default_language"
            ],
        )

    elif script_code == "ar":
        language_code = (
            "ur"
            if market[
                "geo"
            ] == "PK"
            else "ar"
        )

    else:
        language_code = script_code

    profile = language_profile(
        language_code
    )

    return {
        **profile,
        "market_geo": market[
            "geo"
        ],
        "market_name": market[
            "name"
        ],
        "youtube_ad_reach_m": float(
            market.get(
                "youtube_ad_reach_m",
                0.0,
            )
        ),
    }


def market_factor(
    priority_weight: float,
    *,
    share: float,
) -> float:
    """
    Keep trend strength dominant.

    share=0.12 means language-market quality changes at most ~12% of the
    multiplicative final score. A very strong lower-priority language trend
    can still beat a weak English/Hindi trend.
    """
    bounded_priority = max(
        0.0,
        min(
            1.0,
            float(
                priority_weight
            ),
        ),
    )

    bounded_share = max(
        0.0,
        min(
            0.40,
            float(
                share
            ),
        ),
    )

    return (
        1.0
        - bounded_share
        + bounded_share
        * bounded_priority
    )


LOCALE_BY_LANGUAGE = {
    "en": "en_US",
    "hi": "hi_IN",
    "es": "es_ES",
    "pt": "pt_BR",
    "id": "id_ID",
    "ja": "ja_JP",
    "ar": "ar_SA",
    "bn": "bn_BD",
    "fr": "fr_FR",
    "ur": "ur_PK",
    "de": "de_DE",
    "vi": "vi_VN",
    "tr": "tr_TR",
    "ta": "ta_IN",
    "te": "te_IN",
    "mr": "mr_IN",
    "pa": "pa_IN",
    "gu": "gu_IN",
    "kn": "kn_IN",
    "ml": "ml_IN",
    "ru": "ru_RU",
    "zh": "zh_CN",
}

MARKET_LOCALE_OVERRIDES = {
    ("en", "IN"): "en_IN",
    ("en", "US"): "en_US",
    ("es", "MX"): "es_MX",
    ("pt", "BR"): "pt_BR",
    ("id", "ID"): "id_ID",
    ("ja", "JP"): "ja_JP",
    ("ur", "PK"): "ur_PK",
    ("fr", "FR"): "fr_FR",
    ("bn", "BD"): "bn_BD",
    ("ar", "SA"): "ar_SA",
    ("hi", "IN"): "hi_IN",
    ("ta", "IN"): "ta_IN",
    ("te", "IN"): "te_IN",
    ("mr", "IN"): "mr_IN",
    ("pa", "IN"): "pa_IN",
    ("gu", "IN"): "gu_IN",
    ("kn", "IN"): "kn_IN",
    ("ml", "IN"): "ml_IN",
}


def target_locale(
    language_code: str,
    market_geo: str = "",
) -> str:
    language = (
        language_code
        or "en"
    ).strip().lower()

    geo = (
        market_geo
        or ""
    ).strip().upper()

    return MARKET_LOCALE_OVERRIDES.get(
        (
            language,
            geo,
        ),
        LOCALE_BY_LANGUAGE.get(
            language,
            "en_US",
        ),
    )
