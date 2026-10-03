#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

REPORT="$(
  find "$PROJECT/artifacts" \
    -type f \
    -name visual_route_report.jsonl \
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

python - "$REPORT" "$PERF" <<'PY'
import json
import sys
from collections import Counter
from pathlib import Path

route_path = Path(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else None
perf_path = Path(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else None

print("=" * 72)
print("SEMANTIC + PERFORMANCE CHECK")
print("=" * 72)

if route_path and route_path.is_file():
    rows = []
    for line in route_path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            pass

    routes = Counter(row.get("route", "unknown") for row in rows)
    domains = Counter(row.get("domain", "unknown") for row in rows)

    print(f"Scenes       : {len(rows)}")
    print(f"Domains      : {dict(domains)}")
    print(f"Routes       : {dict(routes)}")

    diffusion = sum(
        count
        for name, count in routes.items()
        if str(name).startswith("diffusion")
    )
    editorial = sum(
        count
        for name, count in routes.items()
        if "editorial" in str(name)
        or name in {
            "technical",
            "wikimedia_commons",
        }
    )

    print(f"Diffusion    : {diffusion}")
    print(f"Explainable  : {editorial}")
else:
    print("No visual route report found.")

print()

if perf_path and perf_path.is_file():
    data = json.loads(perf_path.read_text(encoding="utf-8"))
    agents = {
        item.get("agent"): item.get("elapsed_seconds")
        for item in data.get("agents", [])
    }

    print(f"Total        : {data.get('total_elapsed_seconds')} sec")
    print(f"Content plan : {agents.get('Content Production Agent')} sec")
    print(f"Visuals      : {agents.get('Visual Generation Agent')} sec")
    print(f"Video        : {agents.get('Video Assembly Agent')} sec")
    print(f"Peak RSS     : {data.get('process_peak_rss_mb')} MB")
else:
    print("No performance report found.")

print()
print("Visual route report:")
print(f"  {route_path}")
print("Performance report:")
print(f"  {perf_path}")
PY
