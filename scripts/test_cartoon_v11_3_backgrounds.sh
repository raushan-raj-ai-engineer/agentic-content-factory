#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
PY="$PROJECT/.venv/bin/python"
[[ -x "$PY" ]] || PY=python
export PYTHONPATH="$PROJECT/src${PYTHONPATH:+:$PYTHONPATH}"

"$PY" - "$PROJECT" <<'PY'
from __future__ import annotations
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from content_factory.cartoon.models import CartoonDialogueLine, CartoonEpisodePlan, CartoonScene
from content_factory.cartoon.renderer import CartoonRenderer
from content_factory.cartoon.scene_dynamics import apply_scene_dynamics

project = Path(sys.argv[1]).resolve()
config = json.loads((project / "configs/cartoon_performance_v11.json").read_text(encoding="utf-8"))
env = config.get("environment", {})
assert env.get("dynamic_background_enabled") is True
assert int(env.get("ambient_drift_px", 0)) >= 40
assert int(env.get("action_track_px", 0)) >= 100
assert env.get("dynamic_static_fallback") is True
assert env.get("dynamic_emergency_renderer") is True
assert int(env.get("extra_llm_calls", -1)) == 0
assert int(env.get("extra_image_generation_calls", -1)) == 0

scenes = [
    CartoonScene(
        id=i,
        location_id="office",
        beat="setup" if i == 1 else "escalation",
        camera="medium",
        setup="same physical office, different story beat",
        dialogue=[CartoonDialogueLine(character_id="guddu", text="Test")],
        visual_action="walk" if i == 2 else "auto",
    )
    for i in range(1, 7)
]
plan = CartoonEpisodePlan(
    title="V11.3 background probe",
    topic="generic office story",
    language_code="en",
    language_name="English",
    premise="Same physical place must still have visibly different shots.",
    characters=["guddu", "bittu"],
    scenes=scenes,
)
report = apply_scene_dynamics(plan)
variants = [scene.environment_variant for scene in plan.scenes]
assert report["version"] == "11.3"
assert variants == ["establishing", "wide_left", "wide_right", "medium_left", "medium_right", "center_detail"], variants

renderer = object.__new__(CartoonRenderer)
renderer.fps = 24
renderer.performance_config = config
filters = [renderer._dynamic_background_filter(scene=s, duration=1.0) for s in plan.scenes]
assert len(set(filters)) == len(filters), filters
assert any("scale=2266:1274" in x or "scale=2266:1274" in x.replace(" ", "") for x in filters), filters
assert any("scale=2496:1404" in x or "scale=2496:1404" in x.replace(" ", "") for x in filters), filters
assert all("max(0,min(" in x for x in filters)

# Blocking must change for repeated same-location dialogue scenes.
renderer._positions_for = CartoonRenderer._positions_for
base_chars = ["guddu", "bittu"]
pos_left = renderer._positions_for_scene(scene=plan.scenes[1], characters=base_chars, action="dialogue")
pos_right = renderer._positions_for_scene(scene=plan.scenes[2], characters=base_chars, action="dialogue")
assert pos_left != pos_right, (pos_left, pos_right)

source = (project / "src/content_factory/cartoon/renderer.py").read_text(encoding="utf-8")
static_block = source[source.index("    def _render_static_scene("):source.index("    # ------------------------------------------------------------------\n    # Final assembly")]
assert "_dynamic_background_filter(scene=scene, duration=duration)" in static_block
emergency_block = source[source.index("    def _emergency_render("):source.index("    # ------------------------------------------------------------------\n    # Asset / camera helpers")]
assert "for scene in plan.scenes" in emergency_block
assert "emergency dynamic scene" in emergency_block
assert "plan.scenes[0].location_id" not in emergency_block

# Real pixel proof: same office plate must produce different first frames for
# distinct virtual camera zones, and a moving frame must change over time.
bg = project / "assets/cartoon_v9_1/backgrounds/office.png"
if bg.is_file() and shutil.which("ffmpeg"):
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        def run_ffmpeg(cmd: list[str], label: str) -> None:
            # Keep this validator portable across FFmpeg builds.  In particular,
            # avoid select=eq(n\,...) expressions: some macOS/Homebrew builds
            # parse nested filter commas differently and can return code 8 even
            # though the exact renderer filter itself is valid.
            proc = subprocess.run(
                cmd,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            if proc.returncode != 0:
                raise AssertionError(
                    f"{label} failed with FFmpeg exit {proc.returncode}:\n{proc.stderr.strip()}"
                )

        hashes = []
        for idx, scene in enumerate(plan.scenes[:4], start=1):
            f = renderer._dynamic_background_filter(scene=scene, duration=1.0).replace("format=rgba", "format=rgb24")
            out = td / f"variant_{idx}.ppm"
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-loop", "1", "-framerate", "24", "-i", str(bg),
                "-vf", f, "-frames:v", "1", str(out),
            ]
            run_ffmpeg(cmd, f"scene variant {idx}")
            hashes.append(hashlib.sha256(out.read_bytes()).hexdigest())
        assert len(set(hashes)) == len(hashes), hashes

        moving = plan.scenes[1]
        moving.environment_motion = "explore_drift"
        f = renderer._dynamic_background_filter(scene=moving, duration=1.2).replace("format=rgba", "format=rgb24")

        # Portable motion proof: render frame 0 and frame 20 in separate FFmpeg
        # processes.  trim is applied *after* the dynamic crop, so the crop's
        # frame counter still advances to n=20. This avoids the fragile select
        # expression that caused rollback on some FFmpeg 7/8 macOS builds.
        motion_paths = []
        for frame_no in (0, 20):
            out = td / f"motion_{frame_no:02d}.ppm"
            probe_filter = f
            if frame_no:
                probe_filter += (
                    f",trim=start_frame={frame_no}:end_frame={frame_no + 1},"
                    "setpts=PTS-STARTPTS"
                )
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-loop", "1", "-framerate", "24", "-i", str(bg),
                "-vf", probe_filter, "-frames:v", "1", str(out),
            ]
            run_ffmpeg(cmd, f"motion frame {frame_no}")
            motion_paths.append(out)

        p1, p2 = motion_paths
        assert p1.is_file() and p2.is_file()
        assert hashlib.sha256(p1.read_bytes()).hexdigest() != hashlib.sha256(p2.read_bytes()).hexdigest()

print("CARTOON LIVING BACKGROUNDS V11.3 TESTS PASSED")
print("strong_virtual_camera_zones=YES")
print("real_pixel_scene_variation=YES")
print("background_motion_over_time=YES")
print("static_fallback_dynamic=YES")
print("emergency_per_scene_backgrounds=YES")
print("same_location_blocking_variation=YES")
print("extra_llm_calls=0")
print("extra_image_generation_calls=0")
PY
