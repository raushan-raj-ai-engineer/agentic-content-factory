#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

cd "$PROJECT"
source .venv/bin/activate

python - <<'PY'
from content_factory.visual.domain_registry import (
    classify_domain,
)

tests = [
    ("Macará Vs Santos football match", "sports"),
    ("Review Petition Supreme Court hearing", "legal"),
    ("India VIX Today Nifty stock market", "finance"),
    ("Startup acquisition CEO expansion", "business"),
    ("Lok Sabha election campaign", "politics"),
    ("PM Kisan government scheme beneficiary", "public_service"),
    ("Scholarship UP student eligibility application", "education"),
    ("Government job recruitment vacancy", "career"),
    ("CMF Buds Neo earbuds ANC battery life", "product"),
    ("Playwright JavaScript API testing framework", "technical"),
    ("Khalifa Movie Prithviraj trailer", "entertainment"),
    ("GTA gameplay PlayStation update", "gaming"),
    ("New SUV car launch mileage review", "automotive"),
    ("Goa travel guide places to visit", "travel"),
    ("Health advisory symptoms treatment", "health"),
    ("ISRO space mission satellite launch", "science"),
    ("Cyclone weather alert heavy rainfall", "environment"),
    ("Mustard oil cooking recipe", "food"),
    ("Apartment property market home loan", "real_estate"),
    ("History of Magadha ancient dynasty", "history_culture"),
    ("Temple pilgrimage festival ritual", "religion_spirituality"),
    ("Aquarius Horoscope Today", "astrology"),
    ("Skincare makeup beauty tips", "fashion_beauty"),
    ("Kisan crop mandi farming update", "agriculture"),
    ("Cybercrime scam police investigation", "crime_safety"),
    ("Animated kids story fictional character", "creative"),
    ("खाद्य तेल रेसिपी", "food"),
    ("वृश्चिक राशि राशिफल", "astrology"),
    ("अंगणवाडी सरकारी योजना", "public_service"),
    ("छात्रवृत्ति परीक्षा रिजल्ट", "education"),
]

failed = []

print("=" * 78)
print("UNIVERSAL DOMAIN ROUTER V8 TEST")
print("=" * 78)

for text, expected in tests:
    result = classify_domain(
        text
    )
    ok = result.domain == expected

    print(
        f"{'PASS' if ok else 'FAIL'}  "
        f"{expected:<22} <- {text}"
    )

    if not ok:
        failed.append(
            (
                text,
                expected,
                result.to_dict(),
            )
        )

if failed:
    print()
    print("Failures:")
    for item in failed:
        print(item)
    raise SystemExit(1)

print()
print(f"ALL {len(tests)} DOMAIN TESTS PASSED")
PY
