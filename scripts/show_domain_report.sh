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
  echo "No current performance report found."
  exit 0
fi

RUN_DIR="$(dirname "$(dirname "$REPORT")")"
INFO="$RUN_DIR/run_info.json"

python - "$REPORT" "$INFO" "$RUN_DIR" <<'PY'
import json
import sys
from pathlib import Path

perf = Path(sys.argv[1])
info = Path(sys.argv[2])
run_dir = Path(sys.argv[3])

print("=" * 72)
print("CURRENT RUN DOMAIN")
print("=" * 72)
print(f"Run: {run_dir}")

if info.is_file():
    data = json.loads(info.read_text(encoding="utf-8"))
    print(f"Topic: {data.get('topic')}")
else:
    print("Topic: unknown")

# Domain classification lives in workflow state metadata, but not all historical
# run_info schemas persist it. Fall back to reading compact log DOMAIN line.
log_dir = run_dir.parents[2] / "logs" if len(run_dir.parents) >= 3 else None

print()
print("For live classification details, look for:")
print("  [DOMAIN] <domain> family=<family> score=<n> confidence=<n> ...")
PY
