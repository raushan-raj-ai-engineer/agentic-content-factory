#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

REPORT="$(
  find "$PROJECT/artifacts" \
    -type f \
    -name performance_report.json \
    -print 2>/dev/null \
  | xargs -I{} stat -f "%m {}" "{}" 2>/dev/null \
  | sort -nr \
  | head -1 \
  | cut -d' ' -f2-
)"

if [[ -z "${REPORT:-}" || ! -f "$REPORT" ]]; then
  echo "No performance report found."
  exit 0
fi

python - "$REPORT" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(
    path.read_text(
        encoding="utf-8"
    )
)

agents = {
    row.get("agent"): float(
        row.get(
            "elapsed_seconds",
            0,
        )
        or 0
    )
    for row in data.get(
        "agents",
        []
    )
}

print("=" * 68)
print("TREND SPEED REPORT")
print("=" * 68)
print(f"Topic      : {data.get('topic')}")
print(f"Total      : {data.get('total_elapsed_seconds')} sec")
print(f"Trend      : {agents.get('Trend Research Agent', 0):.1f}s")
print(f"Script     : {agents.get('Script Writer Agent', 0):.1f}s")
print(f"Packaging  : {agents.get('Packaging Optimizer Agent', 0):.1f}s")
print(f"Visuals    : {agents.get('Visual Generation Agent', 0):.1f}s")
print(f"Video      : {agents.get('Video Assembly Agent', 0):.1f}s")
print()
print("Report:")
print(f"  {path}")
PY
