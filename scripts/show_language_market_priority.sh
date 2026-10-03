#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

cd "$PROJECT"
source .venv/bin/activate

python - <<'PY'
from content_factory.research.language_market import (
    configured_markets,
    load_language_market_config,
)

config = load_language_market_config()

print("=" * 78)
print("GLOBAL LANGUAGE / YOUTUBE MARKET PRIORITY")
print("=" * 78)

for item in config["languages"]:
    print(
        f"#{item['priority_rank']:>2} "
        f"{item['name']:<20} "
        f"code={item['code']:<3} "
        f"weight={item['priority_weight']:.2f}"
    )

print()
print("Discovery markets:")
for market in configured_markets():
    print(
        f"  {market['geo']:<2} "
        f"{market['name']:<18} "
        f"YouTube reach≈{market['youtube_ad_reach_m']:>6.1f}M "
        f"default_lang={market['default_language']}"
    )
PY
