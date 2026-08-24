#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-/Users/maa/agentic-content-factory}"

RUN="$(
  find "$PROJECT/artifacts" \
    -type f \
    -name "*.shots.json" \
    -print 2>/dev/null \
  | xargs -I{} stat -f "%m {}" "{}" 2>/dev/null \
  | sort -nr \
  | head -1 \
  | cut -d' ' -f2-
)"

if [[ -z "${RUN:-}" || ! -f "$RUN" ]]; then
  echo "No cinematic B-roll shot manifest found yet."
  exit 0
fi

DIR="$(dirname "$RUN")"

python - "$DIR" <<'PY'
import json
import sys
from pathlib import Path

folder = Path(sys.argv[1])

manifests = sorted(
    folder.glob("*.shots.json")
)

print("=" * 72)
print("CINEMATIC B-ROLL REPORT")
print("=" * 72)

total = 0

for manifest in manifests:
    data = json.loads(
        manifest.read_text(
            encoding="utf-8"
        )
    )

    shots = data.get(
        "shots",
        []
    )

    total += len(shots)

    print(
        f"{manifest.name:<36} shots={len(shots)}"
    )

print()
print(f"B-roll scenes : {len(manifests)}")
print(f"Total shots   : {total}")

if manifests and total >= len(manifests) * 2:
    print("Natural shot density: GOOD")
else:
    print("Natural shot density: LIMITED")
PY
