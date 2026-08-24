#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-/Users/maa/agentic-content-factory}"

PERF="$(
  find "$PROJECT/artifacts" \
    -type f \
    -name performance_report.json \
    -print 2>/dev/null \
  | xargs -I{} stat -f "%m {}" "{}" 2>/dev/null \
  | sort -nr \
  | head -1 \
  | cut -d' ' -f2-
)"

if [[ -z "${PERF:-}" || ! -f "$PERF" ]]; then
  echo "No current performance report found."
  exit 0
fi

RUN_DIR="$(dirname "$(dirname "$PERF")")"
QUALITY="$RUN_DIR/visuals/scene_quality_report.jsonl"

if [[ ! -f "$QUALITY" ]]; then
  echo "Current run has no visual quality/route report."
  echo "The run likely stopped before completing Visual Generation."
  echo "Current run:"
  echo "  $RUN_DIR"
  exit 0
fi

python - "$QUALITY" "$RUN_DIR" <<'PY'
import json
import sys
from collections import Counter
from pathlib import Path

path = Path(sys.argv[1])
run_dir = Path(sys.argv[2])
rows = []

for line in path.read_text(encoding="utf-8").splitlines():
    try:
        value = json.loads(line)
    except Exception:
        continue
    if value.get("accepted", True):
        rows.append(value)

routes = Counter(row.get("route", "unknown") for row in rows)
domains = Counter(row.get("domain", "unknown") for row in rows)

print("=" * 72)
print("CURRENT RUN VISUAL ROUTING")
print("=" * 72)
print(f"Run     : {run_dir}")
print(f"Scenes  : {len(rows)}")
print()
print("Routes:")
for name, count in routes.most_common():
    print(f"  {count:3d}  {name}")
print()
print("Domains:")
for name, count in domains.most_common():
    print(f"  {count:3d}  {name}")
print()
print("Quality report:")
print(f"  {path}")
PY
