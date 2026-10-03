#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

cd "$PROJECT"
source .venv/bin/activate

python - <<'PY'
from content_factory.research.language_market import (
    configured_markets,
    detect_language,
    language_profile,
    market_factor,
)
from content_factory.research.trend_signals import (
    DiscoverySignal,
)
from content_factory.agents.research_planner import (
    ResearchPlannerAgent,
)

tests = [
    ("7 Dogs", "IN", "en"),
    ("राजीव गांधी", "IN", "hi"),
    ("ભારતીય ક્રિકેટ ટીમ", "IN", "gu"),
    ("உதயநிதி ஸ்டாலின்", "IN", "ta"),
    ("భారత క్రికెట్ జట్టు", "IN", "te"),
    ("ಭಾರತೀಯ ಕ್ರಿಕೆಟ್ ತಂಡ", "IN", "kn"),
    ("ന്യൂസ്", "IN", "ml"),
    ("bonus saham", "ID", "id"),
    ("Salman Khan", "US", "en"),
    ("mercado hoje", "BR", "pt"),
    ("fútbol mundial", "MX", "es"),
    ("サッカー 日本", "JP", "ja"),
    ("پاکستان کرکٹ", "PK", "ur"),
    ("বাংলাদেশ ক্রিকেট", "BD", "bn"),
    ("السعودية اليوم", "SA", "ar"),
]

for text, geo, expected in tests:
    result = detect_language(
        text,
        geo=geo,
    )

    assert result["code"] == expected, (
        text,
        geo,
        result,
    )

print("Script/market language detection: OK")

assert (
    language_profile("en")[
        "priority_weight"
    ]
    > language_profile("es")[
        "priority_weight"
    ]
    > language_profile("ja")[
        "priority_weight"
    ]
)

assert (
    language_profile("zh")[
        "priority_weight"
    ]
    < language_profile("bn")[
        "priority_weight"
    ]
)

print("Language priority ordering: OK")

markets = configured_markets(10)

assert markets[0]["geo"] == "IN"
assert markets[1]["geo"] == "US"
assert len(markets) == 10

print("Global market ordering: OK")

strong_spanish = DiscoverySignal(
    topic="Strong Spanish Trend",
    score=90.0,
    language_code="es",
    language_name="Spanish",
    language_priority=0.93,
)

weak_english = DiscoverySignal(
    topic="Weak English Trend",
    score=45.0,
    language_code="en",
    language_name="English",
    language_priority=1.00,
)

selected = ResearchPlannerAgent._select_language_diverse(
    [
        strong_spanish,
        weak_english,
    ],
    2,
)

assert selected[0].topic == "Strong Spanish Trend"

print("Trend strength can beat language rank: OK")

factor_low = market_factor(
    0.50,
    share=0.12,
)
factor_high = market_factor(
    1.00,
    share=0.12,
)

assert 0.88 <= factor_low < factor_high <= 1.0

print("Language factor is bounded, not winner-takes-all: OK")

print()
print("GLOBAL LANGUAGE MARKET PRIORITY V8.4 TESTS PASSED")
PY
