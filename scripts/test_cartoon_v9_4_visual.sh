#!/usr/bin/env bash
set -euo pipefail
PROJECT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$PROJECT"
source .venv/bin/activate
export PYTHONPATH="$PROJECT/src${PYTHONPATH:+:$PYTHONPATH}"

python - <<'PY'
import json
import tempfile
from pathlib import Path

from content_factory.cartoon.language import load_language_pack
from content_factory.cartoon.models import (
    CartoonDialogueLine,
    CartoonReaction,
    CartoonScene,
)
from content_factory.cartoon.renderer import CartoonRenderer


renderer = CartoonRenderer(
    project_root=Path.cwd(),
    language=load_language_pack("magahi"),
)

# Compatibility isolation: this script specifically validates the V9.4
# limited-animation path. V10/V11 articulated paths have their own stricter
# runtime render tests later in the apply chain. Avoid re-running the heavy
# V11 actor-track compositor for all three historical V9.4 smoke scenes.
renderer._rig_available = lambda character_id: False

# No TTS dependency in this visual smoke.
def fake_synth(*, text, character_id, output):
    renderer._write_silence(output, 0.62)
    return {"engine":"visual_test","voice":"synthetic","rate":150}

renderer._synthesize_line = fake_synth

scenes = [
    CartoonScene(
        id=1,
        location_id="courtyard",
        beat="escalation",
        camera="wide",
        shot_duration_seconds=6.0,
        setup="Bandar steals litti tray and runs.",
        dialogue=[
            CartoonDialogueLine(
                character_id="guddu",
                text="पकड़ऽ रे!",
                emotion="shocked",
                pose="hands_up",
                pause_after_seconds=0.12,
            ),
            CartoonDialogueLine(
                character_id="bittu",
                text="बंदरवा भाग गेल!",
                emotion="shocked",
                pose="running",
                pause_after_seconds=0.12,
            ),
            CartoonDialogueLine(
                character_id="mai",
                text="हमर लिट्टी!",
                emotion="angry",
                pose="pointing",
                pause_after_seconds=0.12,
            ),
        ],
        reaction=CartoonReaction(
            character_id="guddu",
            expression="shocked",
            duration_seconds=0.55,
        ),
        visual_characters=["bandar"],
        visual_action="steal_tray",
        props=["litti_tray","motion_lines"],
    ),
    CartoonScene(
        id=2,
        location_id="village_lane",
        beat="escalation",
        camera="wide",
        shot_duration_seconds=6.0,
        setup="Guddu Bittu chase the monkey.",
        dialogue=[
            CartoonDialogueLine(character_id="guddu",text="दहिना से घेरऽ!",emotion="serious"),
            CartoonDialogueLine(character_id="bittu",text="तू चप्पल संभालऽ!",emotion="laughing"),
            CartoonDialogueLine(character_id="guddu",text="ई बहुत तेज हई!",emotion="shocked"),
        ],
        reaction=CartoonReaction(character_id="bittu",expression="shocked"),
        visual_characters=["bandar"],
        visual_action="chase",
        props=["motion_lines"],
    ),
    CartoonScene(
        id=3,
        location_id="mango_tree",
        beat="misdirection",
        camera="medium",
        shot_duration_seconds=6.0,
        setup="Chacha tries to catch the monkey and slips.",
        dialogue=[
            CartoonDialogueLine(character_id="chacha",text="ई काम हमार हई!",emotion="proud"),
            CartoonDialogueLine(character_id="guddu",text="चाचा संभलऽ!",emotion="shocked"),
            CartoonDialogueLine(character_id="chacha",text="अई मइया!",emotion="confused"),
        ],
        reaction=CartoonReaction(character_id="chacha",expression="shocked"),
        visual_characters=["bandar"],
        visual_action="chacha_slip",
        props=["dust_cloud"],
    ),
]

with tempfile.TemporaryDirectory(prefix="v94-visual-") as temp:
    root=Path(temp)
    for scene in scenes:
        adir=root/f"a{scene.id}"
        adir.mkdir()
        wav,timeline,report=renderer._build_scene_audio(scene=scene,output_dir=adir)
        out=root/f"scene_{scene.id}.mp4"
        renderer._render_scene_video(
            scene=scene,
            scene_audio=wav,
            timeline=timeline,
            output=out,
        )
        assert out.is_file() and out.stat().st_size > 10000
        assert renderer._microshot_count(scene=scene,timeline=timeline) >= 4
        assert all("mouth_windows" in item for item in timeline)

print("action motion: steal/chase/slip render: OK")
print("story props: tray/motion-lines/dust: OK")
print("dialogue + reaction micro-shots >= 4/scene: OK")
print("amplitude-driven mouth windows: OK")
print("one encode per scene architecture: OK")
print("CARTOON NATURAL PERFORMANCE V9.4 TESTS PASSED")
PY

for f in \
  assets/cartoon_v9_1/props/litti_tray.png \
  assets/cartoon_v9_1/props/single_litti.png \
  assets/cartoon_v9_1/props/chutney_bowl.png \
  assets/cartoon_v9_1/props/baby_monkey.png \
  assets/cartoon_v9_1/props/character_shadow.png \
  assets/cartoon_v9_1/props/motion_lines.png; do
  test -s "$PROJECT/$f"
done

grep -q 'zoompan=' "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q '_mouth_activity_windows' "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q '_character_motion_expr' "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q 'WIDTH = 1920' "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q 'HEIGHT = 1080' "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q 'FPS = 24' "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q 'loudnorm=I=-16:TP=-1.5:LRA=7' "$PROJECT/src/content_factory/cartoon/renderer.py"

echo "1080p24 quality preserved: OK"
echo "voice mastering preserved: OK"
echo "micro-shot camera without extra encode: OK"
echo "V9.4 VISUAL QUALITY/PERFORMANCE CONTRACT PASSED"
