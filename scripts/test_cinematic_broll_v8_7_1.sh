#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-/Users/maa/agentic-content-factory}"

cd "$PROJECT"
source .venv/bin/activate

python - <<'PY'
import inspect
import json
import tempfile
from pathlib import Path

from PIL import Image

from content_factory.agents.content_producer import ContentProductionAgent
from content_factory.visual.public_media import WikimediaCommonsProvider
from content_factory.visual.compositor import PremiumSceneCompositor
from content_factory.visual.local import LocalVisualProvider
from content_factory.video.local import LocalVideoAssembler
from content_factory.visual.semantic_router import decide_visual_route

# Cumulative V8.6.1 protections.
assert hasattr(
    ContentProductionAgent,
    "_ensure_upload_ready_visual_variety",
)
assert hasattr(
    ContentProductionAgent,
    "_resolve_domain_classification",
)

print("V8.6.1 cumulative protections: OK")

# Public provider has one-query multi-shot API.
assert hasattr(
    WikimediaCommonsProvider,
    "fetch_many",
)
sig = inspect.signature(
    WikimediaCommonsProvider.fetch_many
)
assert "output_paths" in sig.parameters
assert "limit" in sig.parameters

print("Multi-shot public-media API: OK")

# Compositor can render pure B-roll with no overlay.
with tempfile.TemporaryDirectory() as td:
    path = Path(td) / "scene_1.png"

    Image.new(
        "RGB",
        (1600, 900),
        (120, 130, 140),
    ).save(path)

    PremiumSceneCompositor().compose_public_photo(
        image_path=path,
        title="Test",
        summary="Test",
        domain="general",
        scene_index=2,
        show_overlay=False,
    )

    with Image.open(path) as image:
        assert image.size == (1920, 1080)

print("Full-screen no-card B-roll compositor: OK")

# Video shot-manifest resolution.
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    primary = root / "scene_1.png"
    shot2 = root / "scene_1.shot02.png"
    shot3 = root / "scene_1.shot03.png"

    for path in (primary, shot2, shot3):
        Image.new(
            "RGB",
            (1920, 1080),
            (100, 100, 100),
        ).save(path)

    primary.with_suffix(
        primary.suffix + ".shots.json"
    ).write_text(
        json.dumps(
            {
                "mode": "cinematic_broll",
                "shots": [
                    {"path": primary.name},
                    {"path": shot2.name},
                    {"path": shot3.name},
                ],
            }
        ),
        encoding="utf-8",
    )

    shots = LocalVideoAssembler._broll_shots(
        str(primary)
    )

    assert len(shots) == 3, shots

print("Video 3-shot manifest: OK")

# Structured scenes remain editorial, hero remains diffusion.
assert decide_visual_route(
    title="Timeline",
    description="timeline",
    prompt="timeline",
    visual_type="timeline_scene",
    context_domain="gaming",
).route == "editorial"

assert decide_visual_route(
    title="Hero",
    description="hero",
    prompt="hero",
    visual_type="gaming_key_art",
    context_domain="gaming",
).route == "diffusion"

print("V8.6.1 mixed visual routing preserved: OK")

# Local provider cache version must invalidate old one-shot cache.
assert LocalVisualProvider.CACHE_VERSION >= 12

print("Old one-shot visual cache invalidated: OK")

print()
print("CINEMATIC B-ROLL V8.7.1 TESTS PASSED")
PY
