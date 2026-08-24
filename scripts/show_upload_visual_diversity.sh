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
  echo "No scene_quality_report.jsonl found."
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
        row = json.loads(line)
    except Exception:
        continue
    if row.get("accepted", True):
        rows.append(row)

routes = Counter(
    str(row.get("route") or "unknown")
    for row in rows
)

print("=" * 72)
print("UPLOAD-READINESS VISUAL ROUTE REPORT")
print("=" * 72)
print(f"Scenes: {len(rows)}")

for route, count in routes.most_common():
    print(f"  {route:<28} {count}")

print()
if len(routes) >= 2:
    print("Route diversity: OK")
else:
    print("Route diversity: LOW")
PY
