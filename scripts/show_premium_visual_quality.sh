#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-/Users/maa/agentic-content-factory}"

REPORT="$(
  find "$PROJECT/artifacts" \
    -type f \
    -name scene_quality_report.jsonl \
    -print 2>/dev/null \
  | xargs -I{} stat -f "%m {}" "{}" 2>/dev/null \
  | sort -nr \
  | head -1 \
  | cut -d' ' -f2-
)"

if [[ -z "${REPORT:-}" || ! -f "$REPORT" ]]; then
  echo "No scene quality report found."
  exit 0
fi

python - "$REPORT" <<'PY'
import json
import sys
from collections import Counter
from pathlib import Path

path = Path(sys.argv[1])
rows = []

for line in path.read_text(encoding="utf-8").splitlines():
    try:
        value = json.loads(line)
    except Exception:
        continue
    if value.get("accepted", True):
        rows.append(value)

routes = Counter(
    row.get("route", "unknown")
    for row in rows
)

print("=" * 68)
print("PREMIUM VISUAL QUALITY REPORT")
print("=" * 68)
print(f"Scenes: {len(rows)}")
print()

for route, count in routes.most_common():
    print(f"{count:3d}  {route}")

scores = [
    float(row["sharpness"])
    for row in rows
    if row.get("sharpness") is not None
]

if scores:
    print()
    print(f"Sharpness avg : {sum(scores)/len(scores):.1f}")
    print(f"Sharpness min : {min(scores):.1f}")
    print(f"Sharpness max : {max(scores):.1f}")

print()
print("Report:")
print(f"  {path}")
PY
