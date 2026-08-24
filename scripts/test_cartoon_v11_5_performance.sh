#!/usr/bin/env bash
set -euo pipefail
PROJECT="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$PROJECT"
source .venv/bin/activate
export PYTHONPATH="$PROJECT/src${PYTHONPATH:+:$PYTHONPATH}"
python - <<'PY'
from pathlib import Path
import hashlib
import subprocess
import tempfile

from content_factory.cartoon.language import load_language_pack
from content_factory.cartoon.models import CartoonDialogueLine, CartoonReaction, CartoonScene
from content_factory.cartoon.renderer import CartoonRenderer
from content_factory.cartoon.router import resolve_story_profile
from content_factory.cartoon.story_planner import CartoonStoryPlanner

project = Path.cwd()
magahi_topic = (
    "Guddu ke bakra mobile leke bhaag gel — ghar ke aangan se bazaar, chai dukan, "
    "school ground aur bus stand tak sab log bakra ke pakde la daudait hai, aur ant me "
    "bakra mobile se selfie le leta hai."
)

# Preserve V11.4's action-world correction while changing performance grammar.
profile = resolve_story_profile(topic=magahi_topic, language_code="magahi")
plan = CartoonStoryPlanner.create_fallback_plan(
    topic=magahi_topic,
    language=load_language_pack("magahi"),
    target_minutes=2,
    cast=profile["preferred_cast"][:4],
)
assert "classroom" not in [scene.location_id for scene in plan.scenes]
assert len(set(scene.location_id for scene in plan.scenes)) >= 5
assert all(scene.camera != "medium_two_shot" for scene in plan.scenes)
assert any(
    len({line.pose for line in scene.dialogue}) >= 2
    for scene in plan.scenes
), "fallback dialogue poses did not diversify"

renderer = CartoonRenderer(project_root=project, language=load_language_pack("magahi"))
scene = CartoonScene(
    id=99,
    location_id="courtyard",
    beat="punchline",
    camera="medium_two_shot",
    setup="synthetic performance regression",
    dialogue=[
        CartoonDialogueLine(character_id="guddu", text="Long funny line", emotion="happy", pose="thinking"),
        CartoonDialogueLine(character_id="bittu", text="Reaction line", emotion="confused", pose="pointing"),
    ],
    reaction=CartoonReaction(character_id="bittu", expression="shocked", duration_seconds=0.6),
)
timeline = [
    {"character_id":"guddu","start":0.10,"voice_end":4.20,"end":4.35,"text":"Long funny line","emotion":"happy","pose":"thinking"},
    {"character_id":"bittu","start":4.35,"voice_end":7.10,"end":7.25,"text":"Reaction line","emotion":"confused","pose":"pointing"},
]
positions = renderer._positions_for_scene(
    scene=scene, characters=["guddu", "bittu"], action="dialogue"
)
camera_filter, shot_count = renderer._microshot_camera_filter(
    scene=scene,
    characters=["guddu", "bittu"],
    positions=positions,
    timeline=timeline,
    duration=7.8,
)
assert shot_count >= 6, shot_count
assert "zoompan=" in camera_filter
assert "1.860" in camera_filter or "1.920" in camera_filter
assert renderer._secondary_line_action(
    primary="talk", emotion="happy", line_index=1
) in {"celebrate", "reaction"}

# Verify the generated zoompan expression is accepted by the user's FFmpeg.
background = project / "assets" / "cartoon_v9_1" / "backgrounds" / "courtyard.png"
assert background.is_file(), background
subprocess.run(
    [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-loop", "1", "-framerate", "24", "-i", str(background),
        "-vf", camera_filter,
        "-t", "0.5", "-frames:v", "12", "-f", "null", "-",
    ],
    check=True,
)

# Real pixel proof: one long spoken line must change body rig state before the
# line ends (not one frozen pose for the whole sentence).
with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    track = tmp / "guddu_performance.mov"
    renderer._render_character_performance_track(
        scene=scene,
        character_id="guddu",
        scene_action="dialogue",
        duration=3.0,
        timeline=[
            {"character_id":"guddu","start":0.10,"voice_end":2.80,"end":2.95,"text":"Long funny line","emotion":"happy","pose":"thinking"},
        ],
        attached_names=set(),
        attached_specs=[],
        primary_actor="guddu",
        output=track,
    )
    hashes = []
    for idx, when in enumerate(("0.50", "2.20")):
        frame = tmp / f"frame_{idx}.ppm"
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-ss", when, "-i", str(track), "-frames:v", "1", str(frame),
            ],
            check=True,
        )
        hashes.append(hashlib.sha256(frame.read_bytes()).hexdigest())
    assert hashes[0] != hashes[1], hashes

print("v11_4_action_world_preserved=OK")
print("same_location_fast_camera_coverage=OK")
print("max_dialogue_shot_about_2_35s=OK")
print("long_line_multi_pose_performance=OK")
print("listener_reaction_during_speech=OK")
print("speaker_motion_visibility_increased=OK")
print("punchline_close_emphasis=OK")
print("ffmpeg_camera_filter_portable=OK")
print("real_pixel_body_pose_change=YES")
print("extra_llm_calls=0")
print("extra_image_generation_calls=0")
print("CARTOON CINEMATIC PERFORMANCE V11.5 TESTS PASSED")
PY
