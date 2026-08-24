#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-/Users/maa/agentic-content-factory}"

cd "$PROJECT"
source .venv/bin/activate

python - <<'PY'
from content_factory.research.topic_quality import (
    is_calendar_only_topic,
)

samples = [
    "21 De Agosto",
    "August 21 2026",
    "Eclipse Lunar De Agosto De 2026",
    "August 21 earthquake",
]

print("=" * 72)
print("TOPIC COHERENCE / ROUTING POLICY")
print("=" * 72)

for topic in samples:
    print(
        f"{topic:<38} "
        f"calendar_only={is_calendar_only_topic(topic)}"
    )

print()
print("Policy:")
print("  bare date/calendar topic -> reject before YouTube validation")
print("  body-only creative marker -> cannot hijack factual video domain")
print("  general factual video -> natural-photo anchors + editorial fallback")
print("  massive script shortfall -> accept truthful shorter duration")
PY
