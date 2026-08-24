#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-/Users/maa/agentic-content-factory}"

cd "$PROJECT"
source .venv/bin/activate

python - <<'PY'
from content_factory.agents.content_producer import (
    ContentProductionAgent,
)

families = [
    ("factual_real_media", "sports"),
    ("lifestyle_real_media", "food"),
    ("factual_editorial", "legal"),
    ("data_finance", "finance"),
    ("product_cinematic", "product"),
    ("technical", "technical"),
    ("creative", "gaming"),
]

print("=" * 76)
print("UNIVERSAL NATURAL VISUAL POLICY")
print("=" * 76)

for family, domain in families:
    photo_scenes = [
        index
        for index in range(
            1,
            11,
        )
        if ContentProductionAgent._use_natural_photo(
            family=family,
            domain=domain,
            scene_index=index,
            block_kind="section",
        )
    ]

    print(
        f"{family:<24} "
        f"domain={domain:<12} "
        f"real-photo anchors={photo_scenes or '-'}"
    )
PY
