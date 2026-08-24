#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
PY="$PROJECT/.venv/bin/python"
[[ -x "$PY" ]] || PY=python
export PYTHONPATH="$PROJECT/src${PYTHONPATH:+:$PYTHONPATH}"

"$PY" - "$PROJECT" <<'PY'
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from content_factory.cartoon.models import (
    CartoonDialogueLine,
    CartoonEpisodePlan,
    CartoonScene,
)
from content_factory.cartoon.router import resolve_story_profile
from content_factory.cartoon.scene_dynamics import apply_scene_dynamics
from content_factory.cartoon.story_planner import CartoonStoryPlanner
from content_factory.cartoon.renderer import CartoonRenderer

project = Path(sys.argv[1]).resolve()

# Topic coverage: no single scenario assumptions. These intentionally span
# different worlds and include the old `sea`/`searches` false-positive case.
topics = {
    "school": "two friends prepare for a school science fair",
    "office": "office team solves a funny printer problem",
    "space": "astronaut searches for a missing tool in space",
    "restaurant": "a chef and customer argue about a strange order",
    "park": "a dog finds a lost ball in the park",
    "fantasy": "mystery adventure in a fantasy castle and forest",
}
profiles = {
    key: resolve_story_profile(topic=value, language_code="english")
    for key, value in topics.items()
}
assert profiles["space"]["locations"] == ["space_station"], profiles["space"]["locations"]
assert "classroom" in profiles["school"]["locations"]
assert "office" in profiles["office"]["locations"]
assert "restaurant" in profiles["restaurant"]["locations"]
assert "park" in profiles["park"]["locations"]
assert "castle" in profiles["fantasy"]["locations"]

# Location candidates become coherent blocks, not A/B/A/B every scene.
arc = CartoonStoryPlanner._coherent_location_arc(
    candidates=["classroom", "school_yard"],
    count=9,
)
assert arc[:5] == ["classroom"] * 5, arc
assert arc[5:] == ["school_yard"] * 4, arc
assert sum(1 for a, b in zip(arc, arc[1:]) if a != b) == 1

# Single-location stories still receive visible environment variation.
scenes = []
for i in range(1, 10):
    scenes.append(
        CartoonScene(
            id=i,
            location_id="office",
            beat=("setup" if i == 1 else "reaction" if i == 7 else "escalation"),
            camera="medium",
            setup="generic story action",
            dialogue=[CartoonDialogueLine(character_id="guddu", text="Hello")],
            visual_action=("walk" if i in {2, 5} else "auto"),
        )
    )
plan = CartoonEpisodePlan(
    title="Generic office test",
    topic="Generic office test",
    language_code="en",
    language_name="English",
    premise="A generic same-location story.",
    characters=["guddu", "bittu"],
    scenes=scenes,
)
report = apply_scene_dynamics(plan)
assert report["topic_agnostic"] is True
assert report["extra_llm_calls"] == 0
assert report["distinct_locations"] == 1
assert len({scene.environment_variant for scene in plan.scenes}) >= 4
assert len({scene.environment_motion for scene in plan.scenes}) >= 3
assert all(scene.continuity_group == "1:office" for scene in plan.scenes)

# Renderer filter must animate a static plate and stay in one FFmpeg pass.
renderer = object.__new__(CartoonRenderer)
renderer.fps = 24
renderer.performance_config = {
    "environment": {
        "dynamic_background_enabled": True,
        "overscan_px": 48,
        "ambient_drift_px": 10,
        "action_track_px": 28,
        "vertical_drift_px": 5,
    }
}
probe_scene = plan.scenes[1]
probe_scene.environment_variant = "left_bias"
probe_scene.environment_motion = "action_track"
filter_text = renderer._dynamic_background_filter(scene=probe_scene, duration=1.0)
assert "crop=1920:1080" in filter_text
assert "sin(n*" in filter_text

ffmpeg = project / "assets" / "cartoon_v9_1" / "backgrounds" / "office.png"
if ffmpeg.is_file():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "dynamic_background_probe.mp4"
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-loop", "1", "-framerate", "24", "-i", str(ffmpeg),
            "-t", "0.75", "-vf", filter_text.replace("format=rgba", "format=yuv420p"),
            "-c:v", "libx264", "-preset", "ultrafast", str(out),
        ]
        try:
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except FileNotFoundError:
            pass
        else:
            assert out.is_file() and out.stat().st_size > 1000

print("CARTOON DYNAMIC SCENES V11.2 TESTS PASSED")
print("topic_agnostic=YES")
print("coherent_location_arcs=YES")
print("same_location_environment_variation=YES")
print("false_world_substring_match_fixed=YES")
print("extra_llm_calls=0")
PY
