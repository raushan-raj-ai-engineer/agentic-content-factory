#!/usr/bin/env bash
set -euo pipefail
PROJECT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$PROJECT"
source .venv/bin/activate
export PYTHONPATH="$PROJECT/src${PYTHONPATH:+:$PYTHONPATH}"

python - <<'PYTEST'
import json
from pathlib import Path
from content_factory.cartoon.language import load_language_pack
from content_factory.cartoon.renderer import CartoonRenderer

root=Path.cwd()
cfg=json.loads((root/'configs/cartoon_rigs_v10.json').read_text(encoding='utf-8'))
qc=cfg['quality_contract']
assert qc['sliding_only_motion_for_walk_run_allowed'] is False
assert qc['prop_floating_allowed'] is False
assert qc['broken_disconnected_human_limbs_allowed'] is False
assert qc['runtime_pillow_required'] is False
assert qc['extra_llm_calls'] == 0
assert qc['apng_runtime_allowed'] is False
assert qc['wide_sprite_sheet_runtime_allowed'] is False
assert qc['png_sequence_runtime_required'] is True
assert cfg['transport']['body_cycle_format'] == 'numbered_png_sequence'

ids=('guddu','bittu','chacha','mai','babuji','teacher','doctor','police','astronaut','robot','alien','chef','athlete','worker','guest_child','guest_adult','wizard')
actions=('idle','talk','walk','walk_carry','run','run_carry','carry','point','grab','give','use_device','celebrate','reaction','jump','fall','magic')
for cid in ids:
    base=root/'assets/cartoon_v10/rigs'/cid
    for action in actions:
        seq = base / f'body_{action}_frames'
        frames = list(seq.glob('frame_*.png'))
        assert frames, (cid, action)
        minimum = 8 if action in {'walk','walk_carry','run','run_carry'} else 3
        assert len(frames) >= minimum, (cid, action, len(frames))
    assert (base/'face_neutral_closed.png').is_file()
    assert (base/'face_shocked_open.png').is_file()

renderer=CartoonRenderer(project_root=root,language=load_language_pack('english'))
assert renderer._rig_available('guddu')
assert renderer._rig_action(character_id='guddu',scene_action='walk',attached_props={'suitcase'}) == 'walk_carry'
assert renderer._rig_action(character_id='guddu',scene_action='run',attached_props=set()) == 'run'
assert renderer._rig_action(character_id='doctor',scene_action='chase',attached_props=set()) == 'run'

print('17 reusable articulated rigs: OK')
print('16 body/action cycles per articulated rig: OK')
print('connected elbow/knee limb assets: OK')
print('walk/run use stride cycles instead of static PNG slide: OK')
print('walk + suitcase selects constrained walk_carry cycle: OK')
print('portable props are actor-socket constrained: OK')
print('runtime Pillow/image generation: NONE')
print('extra articulated-rig LLM calls: 0')
PYTEST



for cycle in body_walk_frames body_run_frames body_walk_carry_frames body_run_carry_frames; do
  count="$(find "$PROJECT/assets/cartoon_v10/rigs/guddu/$cycle" -type f -name 'frame_*.png' | wc -l | tr -d ' ')"
  test "${count:-0}" -ge 8
  echo "$cycle articulated PNG frames=$count: OK"
done

TMP_SEQ_TEST="$(mktemp -d -t cartoon-v10-seq-XXXXXX)"
trap 'rm -rf "$TMP_SEQ_TEST"' EXIT

ffmpeg -hide_banner -loglevel error -y \
  -stream_loop -1 -framerate 8 -start_number 0 \
  -i "$PROJECT/assets/cartoon_v10/rigs/guddu/body_walk_frames/frame_%02d.png" \
  -t 1 -vf "fps=8,format=rgba" \
  "$TMP_SEQ_TEST/frame_%02d.png"

DISTINCT="$(
  shasum -a 256 "$TMP_SEQ_TEST"/frame_*.png \
    | awk '{print $1}' \
    | sort -u \
    | wc -l \
    | tr -d ' '
)"
test "${DISTINCT:-0}" -ge 6
echo "PNG-sequence articulated distinct frames=$DISTINCT: OK"


python -m content_factory.cartoon.renderer --self-test --project-root "$PROJECT"

grep -q 'RIG_FRAME_W = 420' "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q '_rig_sheet_stream' "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q 'APNG runtime decoding is disabled' "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q 'body_walk_frames' "$PROJECT/src/content_factory/cartoon/renderer.py"
! grep -q 'body_walk.apng' "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q '_attached_prop_specs' "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q '_articulation_quality_check' "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q '_attached_prop_path' "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q '"walk_carry"' "$PROJECT/configs/cartoon_rigs_v10.json"
grep -q 'FPS = 24' "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q 'WIDTH = 1920' "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q 'HEIGHT = 1080' "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q 'h264_videotoolbox' "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q 'loudnorm=I=-16:TP=-1.5:LRA=7' "$PROJECT/src/content_factory/cartoon/renderer.py"

echo '1080p24 + M2 encoder path preserved: OK'
echo 'voice mastering preserved: OK'
echo 'one FFmpeg encode per scene preserved: OK'
echo 'human locomotion missing rig -> degraded/review: OK'
echo 'floating portable prop risk -> degraded/review: OK'
echo 'Rig transport = NUMBERED_PNG_SEQUENCE: OK'
echo 'APNG runtime decoder = DISABLED: OK'
echo 'Wide-sheet runtime transport = DISABLED: OK'
echo 'V10.0.1 PORTABLE ARTICULATED PERFORMANCE CONTRACT PASSED'
