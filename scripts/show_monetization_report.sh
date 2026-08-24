#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-/Users/maa/agentic-content-factory}"

LATEST_LOG="$(
  find "$PROJECT/logs" \
    -maxdepth 1 \
    -type f \
    -name 'content-factory-*.log' \
    -print 2>/dev/null \
  | xargs -I{} stat -f "%m {}" "{}" 2>/dev/null \
  | sort -nr \
  | head -1 \
  | cut -d' ' -f2-
)"

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

if [[ -z "${LATEST_LOG:-}" || ! -f "$LATEST_LOG" ]]; then
  echo "No current Content Factory log found."
  exit 0
fi

LOG_MTIME="$(stat -f "%m" "$LATEST_LOG")"

if [[ -z "${PERF:-}" || ! -f "$PERF" ]]; then
  echo "Current run did not reach artifact/performance reporting."
  echo "Not showing a stale monetization report."
  echo "Current log:"
  echo "  $LATEST_LOG"
  exit 0
fi

PERF_MTIME="$(stat -f "%m" "$PERF")"

# If the newest log began after the newest performance report, the latest run
# failed before producing a run artifact. Never pretend the older artifact is
# the current run.
if (( LOG_MTIME > PERF_MTIME + 2 )); then
  echo "Current run did not reach the Monetization Safety Gate."
  echo "Not showing a stale report from an older topic."
  echo "Current log:"
  echo "  $LATEST_LOG"
  exit 0
fi

RUN_DIR="$(dirname "$(dirname "$PERF")")"
REPORT="$RUN_DIR/monetization/monetization_report.json"

if [[ ! -f "$REPORT" ]]; then
  echo "Current run did not reach the Monetization Safety Gate."
  echo "No monetization report exists for:"
  echo "  $RUN_DIR"
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

print("=" * 64)
print("MONETIZATION SAFETY REPORT")
print("=" * 64)
print(f"Topic        : {data.get('topic')}")
print(f"Risk         : {data.get('risk_level')}")
print(f"Upload ready : {data.get('upload_ready')}")
print(
    "AI disclosure: "
    f"{data.get('ai_disclosure', {}).get('decision')}"
)
print(f"Fact check   : {data.get('fact_check_passed')}")
print()

for label, key in (
    ("BLOCKS", "hard_blocks"),
    ("HIGH RISKS", "high_risks"),
    ("REVIEW", "warnings"),
    ("ACTIONS", "required_actions"),
):
    values = data.get(key) or []

    if not values:
        continue

    print(label)

    for value in values:
        print(f"  - {value}")

    print()

print("Report:")
print(f"  {path}")
print("Checklist:")
print(
    f"  {path.parent / 'YOUTUBE_UPLOAD_CHECKLIST.md'}"
)
PY
