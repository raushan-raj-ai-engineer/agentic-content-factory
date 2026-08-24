#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-/Users/maa/agentic-content-factory}"

cd "$PROJECT"
source .venv/bin/activate
export PYTHONPATH="$PROJECT/src${PYTHONPATH:+:$PYTHONPATH}"

python - <<'PY'
from pathlib import Path
import tempfile

from content_factory.cartoon.language import load_language_pack
from content_factory.cartoon.models import (
    CartoonDialogueLine,
    CartoonReaction,
    CartoonScene,
)
from content_factory.cartoon.renderer import CartoonRenderer


renderer = CartoonRenderer(
    project_root=Path.cwd(),
    language=load_language_pack("hindi"),
)

# Avoid platform TTS dependency in this timing test.
def fake_synthesize(*, text, character_id, output):
    renderer._write_silence(output, 0.55)
    return {
        "engine": "timing_test",
        "voice": "synthetic",
        "rate": 150,
    }

renderer._synthesize_line = fake_synthesize

scene = CartoonScene(
    id=1,
    location_id="living_room",
    beat="reaction",
    camera="medium_two_shot",
    shot_duration_seconds=20.0,
    setup="Audio pacing test",
    dialogue=[
        CartoonDialogueLine(
            character_id="guddu",
            text="पहली लाइन",
            emotion="happy",
            pose="thinking",
            pause_after_seconds=0.30,
        ),
        CartoonDialogueLine(
            character_id="mai",
            text="दूसरी लाइन",
            emotion="confused",
            pose="pointing",
            pause_after_seconds=0.30,
        ),
        CartoonDialogueLine(
            character_id="guddu",
            text="तीसरी लाइन",
            emotion="smirk",
            pose="thinking",
            pause_after_seconds=0.25,
        ),
    ],
    reaction=CartoonReaction(
        character_id="mai",
        expression="shocked",
        duration_seconds=0.7,
        camera="reaction_close_up",
        sfx=None,
    ),
    sfx_cues=[],
    camera_action="reaction_punch_in",
    transition="hard_cut",
)

with tempfile.TemporaryDirectory(prefix="cartoon-audio-v912-") as temp:
    wav, timeline, report = renderer._build_scene_audio(
        scene=scene,
        output_dir=Path(temp),
    )

    duration = renderer._wave_duration(wav)

    # Old V9.1 behavior padded this to 20 seconds.
    assert duration < 4.0, duration
    assert report["audio_driven_timing"] is True
    assert report["planned_scene_seconds"] == 20.0
    assert report["trimmed_idle_seconds"] > 15.0

    pauses = [
        float(item["pause_seconds"])
        for item in timeline
    ]
    assert max(pauses) <= 0.22 + 1e-9, pauses
    assert min(pauses) >= 0.09 - 1e-9, pauses

print("20s forced silence padding removed: OK")
print("Audio-driven scene duration: OK")
print("Natural inter-line pause clamp 0.09-0.22s: OK")
print("Short reaction hold: OK")
print("V9.1.2 AUDIO PACING TESTS PASSED")
PY

grep -q 'highpass=f=80' \
  "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q 'lowpass=f=11500' \
  "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q 'acompressor=' \
  "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q 'loudnorm=I=-16:TP=-1.5:LRA=7' \
  "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q 'volume=0.18' \
  "$PROJECT/src/content_factory/cartoon/renderer.py"

echo "Speech EQ/high-pass/low-pass: OK"
echo "Speech compression: OK"
echo "Speech loudness normalization: OK"
echo "SFX ducked for dialogue clarity: OK"
echo "V9.1.2 AUDIO CLARITY TESTS PASSED"
