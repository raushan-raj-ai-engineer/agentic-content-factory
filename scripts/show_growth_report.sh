#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-/Users/maa/agentic-content-factory}"
TOPIC="${2:-}"

cd "$PROJECT"

if [[ -n "$TOPIC" ]]; then
  SLUG="$(python - "$TOPIC" <<'PY'
import re
import sys
value = sys.argv[1].strip().lower()
print(re.sub(r"[^a-z0-9]+", "-", value).strip("-"))
PY
)"
  BASE="$PROJECT/artifacts/$SLUG"
else
  BASE="$PROJECT/artifacts"
fi

REPORT="$(find "$BASE" -type f -name growth_readiness_report.json -print 2>/dev/null \
  | xargs -I{} stat -f "%m {}" "{}" 2>/dev/null \
  | sort -nr \
  | head -1 \
  | cut -d' ' -f2-)"

if [[ -z "${REPORT:-}" || ! -f "$REPORT" ]]; then
  echo "No growth readiness report found."
  exit 0
fi

python - "$REPORT" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))

print("=" * 64)
print("YOUTUBE GROWTH READINESS")
print("=" * 64)
print(f"Topic        : {data.get('topic')}")
print(f"Overall      : {data.get('overall_score')}/100")
print(f"Status       : {data.get('label')}")
print(f"Appeal       : {data.get('appeal', {}).get('score')}/100")
print(f"Engagement   : {data.get('engagement', {}).get('score')}/100")
print(f"Satisfaction : {data.get('satisfaction', {}).get('score')}/100")
print()

for section in ("appeal", "engagement", "satisfaction"):
    info = data.get(section, {})
    notes = info.get("notes") or []
    if notes:
        print(section.upper())
        for note in notes:
            print(f"  - {note}")
        print()

print("Report:")
print(f"  {path}")
print("A/B plan:")
print(f"  {path.parent / 'YOUTUBE_AB_TEST_PLAN.md'}")
print("Shorts plan:")
print(f"  {path.parent / 'SHORTS_REPURPOSE_PLAN.md'}")
PY
