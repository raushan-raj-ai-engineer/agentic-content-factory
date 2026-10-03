#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$PROJECT"
source .venv/bin/activate
export PYTHONPATH="$PROJECT/src${PYTHONPATH:+:$PYTHONPATH}"

python - <<'PY'
import json
import tempfile
import wave
from pathlib import Path

from content_factory.cartoon.models import (
    CartoonDialogueLine,
    CartoonEpisodePlan,
    CartoonReaction,
    CartoonScene,
)
from content_factory.cartoon.monetization import (
    BLOCK,
    PASS,
    REVIEW,
    run_post_render_gate,
    run_pre_render_gate,
)


def scene(i, beat, text):
    return CartoonScene(
        id=i,
        location_id="courtyard",
        beat=beat,
        camera="medium",
        shot_duration_seconds=6.0,
        setup=f"Unique setup event number {i}: {text}",
        dialogue=[
            CartoonDialogueLine(
                character_id="guddu",
                text=f"Guddu unique line {i}: {text}",
                emotion="happy",
                pose="idle",
            ),
            CartoonDialogueLine(
                character_id="bittu",
                text=f"Bittu different response {i}: now event {i} changes.",
                emotion="confused",
                pose="idle",
            ),
        ],
        reaction=CartoonReaction(
            character_id="mai",
            expression="shocked",
        ),
    )


with tempfile.TemporaryDirectory(prefix="v93-monetization-") as temp:
    root = Path(temp)
    (root / "configs").mkdir(parents=True)
    (root / "artifacts" / "cartoon").mkdir(parents=True)
    source_policy = (
        Path.cwd() / "configs" / "cartoon_monetization.json"
    )
    (root / "configs" / "cartoon_monetization.json").write_text(
        source_policy.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    plan = CartoonEpisodePlan(
        title="Litti Chor Bandar",
        topic="Litti Chor Bandar",
        language_code="magahi",
        language_name="Magahi",
        genre="animal_comedy",
        route="animal_comedy",
        audience="kids",
        story_tags=["food", "village", "kids", "chase", "wholesome"],
        premise=(
            "A naughty monkey takes litti. Guddu and Bittu chase him. "
            "They finally understand he is feeding his baby and Mai shares food."
        ),
        characters=["guddu", "bittu", "mai", "chacha", "bandar"],
        scenes=[
            scene(1, "setup", "Mai cooks litti and monkey notices it"),
            scene(2, "setup", "monkey moves closer while kids notice"),
            scene(3, "escalation", "monkey takes the tray and chase starts"),
            scene(4, "escalation", "kids try a new path to catch monkey"),
            scene(5, "misdirection", "Chacha tries hero plan and slips"),
            scene(6, "escalation", "Bittu uses a bait plan differently"),
            scene(7, "reaction", "litti chaos surprises everyone"),
            scene(8, "reaction", "they learn monkey feeds his baby"),
            scene(9, "callback", "Mai shares and monkey gets last litti"),
        ],
        ending_callback="Monkey harmlessly takes one final litti.",
    )
    artifact = root / "artifacts" / "cartoon" / "litti" / "run1"
    story = artifact / "story"
    story.mkdir(parents=True)
    plan_path = story / "episode_plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    pre = run_pre_render_gate(
        project_root=root,
        plan=plan,
        plan_path=plan_path,
    )
    assert pre.decision == PASS, pre.report
    assert pre.made_for_kids is True
    assert pre.report["performance"]["llm_calls_added"] == 0
    assert pre.report["performance"]["quality_settings_changed"] is False

    # Create a clean 2-second WAV with tone (not silent/clipped).
    audio = artifact / "audio" / "master.wav"
    audio.parent.mkdir(parents=True)
    with wave.open(str(audio), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        frames = bytearray()
        for i in range(96000):
            value = int(5000 * __import__("math").sin(2 * __import__("math").pi * 220 * i / 48000))
            frames.extend(int(value).to_bytes(2, "little", signed=True))
        wav.writeframes(bytes(frames))

    render_report = artifact / "render_report.json"
    render_report.write_text(
        json.dumps(
            {
                "voice_engine": "macos_say",
                "duration_match": True,
                "duration_delta_seconds": 0.01,
                "degraded": False,
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )

    post = run_post_render_gate(
        project_root=root,
        plan=plan,
        plan_path=plan_path,
        render_report_path=render_report,
        master_audio_path=audio,
        pre_result=pre,
    )
    assert post.decision == PASS, post.report
    assert post.upload_ready is True

    # Same story copied as another episode should now be blocked by history.
    artifact2 = root / "artifacts" / "cartoon" / "copy" / "run2"
    story2 = artifact2 / "story"
    story2.mkdir(parents=True)
    plan2_path = story2 / "episode_plan.json"
    plan2_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    repeated = run_pre_render_gate(
        project_root=root,
        plan=plan,
        plan_path=plan2_path,
    )
    assert repeated.decision == BLOCK, repeated.report

    # Kids + strong adult term must block.
    unsafe = plan.model_copy(
        update={
            "premise": "Kids cartoon involving whisky and cigarette smoking."
        }
    )
    unsafe_path = root / "unsafe.json"
    unsafe_path.write_text(unsafe.model_dump_json(indent=2), encoding="utf-8")
    unsafe_gate = run_pre_render_gate(
        project_root=root,
        plan=unsafe,
        plan_path=unsafe_path,
    )
    assert unsafe_gate.decision == BLOCK

print("clean original kids episode -> PASS: OK")
print("post-render clear audio + duration -> PASS: OK")
print("identical second episode -> BLOCK_UPLOAD: OK")
print("kids + mature themes -> BLOCK_UPLOAD: OK")
print("made-for-kids recommendation: OK")
print("0 extra LLM calls: OK")
print("quality settings changed: NO")
print("CARTOON MONETIZATION V9.3 TESTS PASSED")
PY

grep -q 'h264_videotoolbox' \
  "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q 'loudnorm=I=-16:TP=-1.5:LRA=7' \
  "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q 'FPS = 24' \
  "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q 'WIDTH = 1920' \
  "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q 'HEIGHT = 1080' \
  "$PROJECT/src/content_factory/cartoon/renderer.py"

echo "1080p24 renderer quality settings preserved: OK"
echo "voice mastering/loudnorm preserved: OK"
echo "M2 h264_videotoolbox path preserved: OK"
echo "V9.3 QUALITY-PRESERVING PERF CONTRACT PASSED"
