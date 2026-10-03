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

print("=" * 68)
print("CONTENT FACTORY PERFORMANCE")
print("=" * 68)
print(f"Topic      : {data.get('topic')}")
print(f"Run ID     : {data.get('run_id')}")
print(f"Total      : {data.get('total_elapsed_seconds')} sec")
print(f"Peak RSS   : {data.get('process_peak_rss_mb')} MB")
print()

rows = sorted(
    data.get("agents", []),
    key=lambda row: row.get(
        "elapsed_seconds",
        0,
    ),
    reverse=True,
)

print("Slowest agents:")
for row in rows[:10]:
    print(
        f"  {row.get('elapsed_seconds', 0):8.1f}s  "
        f"{row.get('agent')}"
    )

print()
print("Report:")
print(f"  {path}")
PY
