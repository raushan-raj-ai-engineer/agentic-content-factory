#!/usr/bin/env bash
set -euo pipefail
PROJECT="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$PROJECT"
source .venv/bin/activate
export PYTHONPATH="$PROJECT/src${PYTHONPATH:+:$PYTHONPATH}"
python - <<'PY'
from pathlib import Path

from content_factory.cartoon.capabilities import (
    resolve_action_families,
    resolve_background_asset_id,
)
from content_factory.cartoon.language import load_language_pack
from content_factory.cartoon.models import CartoonDialogueLine, CartoonScene
from content_factory.cartoon.router import (
    resolve_explicit_location_sequence,
    resolve_story_profile,
    route_topic,
)
from content_factory.cartoon.story_planner import CartoonStoryPlanner

project = Path.cwd()
exact_topic = (
    "Guddu ke bakra mobile leke bhaag gel — ghar ke aangan se bazaar, chai dukan, "
    "school ground aur bus stand tak sab log bakra ke pakde la daudait hai, aur ant me "
    "bakra mobile se selfie le leta hai."
)
expected_explicit = ["courtyard", "market", "tea_shop", "school_yard", "bus_stop"]

# 1) Routing: Romanized Magahi chase must outrank incidental school mention.
assert route_topic(exact_topic).primary == "adventure_chase"
assert resolve_explicit_location_sequence(exact_topic) == expected_explicit
assert resolve_action_families(exact_topic)[0] == "chase"

# 2) Cast: school ground must not inject teacher unless teacher is explicitly named.
profile = resolve_story_profile(topic=exact_topic, language_code="magahi")
assert profile["action_story"] is True
assert profile["forced_location_arc"] == expected_explicit
assert profile["preferred_cast"][:2] == ["guddu", "bittu"]
assert "teacher" not in profile["preferred_cast"]
assert profile["primary_action"] == "chase"
assert profile["opening_action"] == "grab"
assert profile["ending_action"] == "use_device"
assert profile["topic_props"] == ["phone"]

# 3) Full deterministic fallback: same structural plan as normal planning.
plan = CartoonStoryPlanner.create_fallback_plan(
    topic=exact_topic,
    language=load_language_pack("magahi"),
    target_minutes=2,
    cast=profile["preferred_cast"][:4],
)
assert len(plan.scenes) == 6
assert "teacher" not in plan.characters
assert plan.characters[:2] == ["guddu", "bittu"]

# Direct places must all survive in order. Extra scene may repeat one place,
# but explicit places may not be collapsed to classroom/one world.
compressed = []
for scene in plan.scenes:
    if not compressed or compressed[-1] != scene.location_id:
        compressed.append(scene.location_id)
assert compressed == expected_explicit, compressed
assert "classroom" not in [scene.location_id for scene in plan.scenes]
assert len(set(scene.location_id for scene in plan.scenes)) >= 5

# 4) Action/blocking/camera contract survives fallback.
assert [scene.visual_action for scene in plan.scenes] == [
    "grab", "chase", "chase", "search", "chase", "use_device"
]
assert [scene.blocking_mode for scene in plan.scenes] == [
    "action_exchange", "moving_chase", "moving_chase", "moving_group", "moving_chase", "prop_focus"
]
assert all(scene.camera != "medium_two_shot" for scene in plan.scenes)
assert all("phone" in scene.props for scene in plan.scenes)
assert all(
    "motion_lines" in scene.props
    for scene in plan.scenes
    if scene.visual_action == "chase"
)
assert all(len(scene.visual_characters) >= 3 for scene in plan.scenes)

# 5) Old generic career fallback must never leak into a route/action story.
forbidden = ("करियर", "नौकरी", "career", "job title", "पहिला कमाई")
assert not any(
    token.casefold() in line.text.casefold()
    for scene in plan.scenes
    for line in scene.dialogue
    for token in forbidden
)

# 6) Hard background switching: every explicit location resolves to its own
# bundled asset rather than reusing classroom/blackboard.
resolved = [resolve_background_asset_id(scene.location_id) for scene in plan.scenes]
assert resolved == [scene.location_id for scene in plan.scenes]
for location in expected_explicit:
    assert (project / "assets" / "cartoon_v9_1" / "backgrounds" / f"{location}.png").is_file(), location

# 7) Explicit specialized role is preserved: the filter only removes implicit
# world-role pollution.
teacher_topic = "Teacher runs from classroom to bus stand chasing a student"
teacher_profile = resolve_story_profile(topic=teacher_topic, language_code="english")
assert teacher_profile["forced_location_arc"] == ["classroom", "bus_stop"]
assert teacher_profile["preferred_cast"][0] == "teacher"

# 8) Non-action school stories keep normal school behavior.
school_topic = "Teacher explains homework in classroom"
school_profile = resolve_story_profile(topic=school_topic, language_code="english")
assert school_profile["action_story"] is False
assert "teacher" in school_profile["preferred_cast"]
assert route_topic(school_topic).primary == "school_comedy"

# 9) Generic action story remains topic-agnostic; no Magahi-only hardcoding.
doctor_topic = "Doctor runs from hospital to airport carrying a suitcase"
doctor_profile = resolve_story_profile(topic=doctor_topic, language_code="english")
assert doctor_profile["forced_location_arc"] == ["hospital", "airport"]
assert doctor_profile["preferred_cast"][0] == "doctor"
assert doctor_profile["primary_action"] == "run"
assert "suitcase" in doctor_profile["topic_props"]

chef_topic = "A chef carries food from kitchen to restaurant"
chef_profile = resolve_story_profile(topic=chef_topic, language_code="english")
assert route_topic(chef_topic).primary == "food_comedy"
assert chef_profile["forced_location_arc"] == ["kitchen", "restaurant"]
assert chef_profile["preferred_cast"][0] == "chef"
assert chef_profile["primary_action"] == "carry"

# 10) Backward compatibility: old saved scenes omit blocking_mode and receive
# the safe default rather than failing Pydantic validation.
legacy_scene = CartoonScene(
    id=1,
    location_id="courtyard",
    beat="setup",
    camera="medium_two_shot",
    setup="legacy scene",
    dialogue=[CartoonDialogueLine(character_id="guddu", text="hello")],
)
assert legacy_scene.blocking_mode == "auto"

# 11) Long-topic bounds remain intact after the structural changes.
long_topic = (exact_topic + " मगही मजेदार कहानी ") * 20
long_profile = resolve_story_profile(topic=long_topic, language_code="magahi")
long_plan = CartoonStoryPlanner.create_fallback_plan(
    topic=long_topic,
    language=load_language_pack("magahi"),
    target_minutes=2,
    cast=long_profile["preferred_cast"][:4],
)
assert len(long_plan.title) <= 120
assert len(long_plan.premise) <= 800
assert all(len(scene.setup) <= 500 for scene in long_plan.scenes)

# 12) The degraded/static renderer must no longer be two frozen sprites. Render
# one short chase scene and prove the pixels change over time. Use two separate
# ffmpeg seeks instead of the fragile select-filter validator used by V11.3.
import hashlib
import subprocess
import tempfile
import wave
from content_factory.cartoon.renderer import CartoonRenderer

with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    wav_path = tmp / "silence.wav"
    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(b"\x00\x00" * 48000)

    chase_scene = plan.scenes[1].model_copy(deep=True)
    chase_scene.shot_duration_seconds = 1.0
    out = tmp / "static_action.mp4"
    timeline = [
        {"character_id": "guddu", "start": 0.0, "voice_end": 0.35, "end": 0.42},
        {"character_id": "bittu", "start": 0.48, "voice_end": 0.82, "end": 0.90},
    ]
    renderer = CartoonRenderer(
        project_root=project,
        language=load_language_pack("magahi"),
    )
    renderer._render_static_scene(
        scene=chase_scene,
        scene_audio=wav_path,
        timeline=timeline,
        output=out,
    )
    assert out.is_file() and out.stat().st_size > 10000

    frames = []
    for index, when in enumerate(("0.05", "0.65")):
        frame = tmp / f"frame_{index}.ppm"
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-ss", when, "-i", str(out), "-frames:v", "1", str(frame),
            ],
            check=True,
        )
        frames.append(hashlib.sha256(frame.read_bytes()).hexdigest())
    assert frames[0] != frames[1], frames

print("exact_magahi_route_adventure_chase=OK")
print("explicit_location_arc_preserved=OK")
print("incidental_school_teacher_removed=OK")
print("explicit_teacher_preserved=OK")
print("fallback_action_camera_blocking=OK")
print("fallback_career_dialogue_leak_removed=OK")
print("phone_prop_persistence=OK")
print("chase_motion_lines=OK")
print("multi_actor_visual_participation=OK")
print("hard_background_asset_switch=OK")
print("static_fallback_multi_actor_motion=OK")
print("generic_english_action_topics=OK")
print("non_action_school_compatibility=OK")
print("legacy_plan_compatibility=OK")
print("long_topic_schema_bounds_preserved=OK")
print("CARTOON ACTION WORLD V11.4 TESTS PASSED")
PY
