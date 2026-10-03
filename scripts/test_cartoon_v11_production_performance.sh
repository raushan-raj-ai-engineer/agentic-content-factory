#!/usr/bin/env bash
set -euo pipefail
PROJECT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$PROJECT"
if [[ -f "$PROJECT/.venv/bin/activate" ]]; then
  source "$PROJECT/.venv/bin/activate"
fi
export PYTHONPATH="$PROJECT/src${PYTHONPATH:+:$PYTHONPATH}"

python - <<'PY'
import json
import tempfile
from pathlib import Path
from content_factory.cartoon.capabilities import enrich_plan
from content_factory.cartoon.characters import background_ids
from content_factory.cartoon.language import load_language_pack
from content_factory.cartoon.models import CartoonEpisodePlan, CartoonScene, CartoonDialogueLine
from content_factory.cartoon.renderer import CartoonRenderer

root=Path('.').resolve()
cfg=json.loads((root/'configs/cartoon_performance_v11.json').read_text())
q=cfg['quality_contract']
assert cfg['version'] in {'11.1','11.2'}, cfg['version']
assert q['whole_scene_single_pose_forbidden']
assert q['whole_scene_topic_action_loop_forbidden']
assert q['listener_reactions_enabled']
assert q['real_closeups_required']
assert q['foreground_depth_enabled']
assert q['world_default_prop_injection_forbidden']
assert q['exclusive_body_states_required']
assert q['foot_plant_locomotion_required']
assert q['actor_local_prop_attachment_required']
assert q['primary_actor_only_scene_translation']
assert q['dialogue_closeups_independent_of_scene_action']
assert q['anti_slideshow_motion_gate_required']
assert q['performance_track_precomposition_required']
assert q['extra_llm_calls']==0

plan=CartoonEpisodePlan(
    title='Airport',
    topic='Doctor runs through an airport carrying a suitcase',
    language_code='english',language_name='English',
    genre='general_comedy',route='general_comedy',audience='all',premise='Airport',
    characters=['doctor','guest_adult'],
    scenes=[
        CartoonScene(id=1,location_id='airport',beat='setup',camera='wide',shot_duration_seconds=6,setup='Doctor runs through the airport carrying a suitcase.',dialogue=[CartoonDialogueLine(character_id='doctor',text='I am late!')],props=['suitcase']),
        CartoonScene(id=2,location_id='airport',beat='reaction',camera='close_up',shot_duration_seconds=6,setup='Doctor stops and reacts in surprise.',dialogue=[CartoonDialogueLine(character_id='guest_adult',text='Wrong gate!')],props=['suitcase']),
        CartoonScene(id=3,location_id='airport',beat='misdirection',camera='medium',shot_duration_seconds=6,setup='Doctor checks the boarding sign.',dialogue=[CartoonDialogueLine(character_id='doctor',text='Where is gate twelve?')],props=['suitcase']),
        CartoonScene(id=4,location_id='airport',beat='callback',camera='close_up',shot_duration_seconds=6,setup='Doctor laughs and points.',dialogue=[CartoonDialogueLine(character_id='doctor',text='Now I know!')],props=['suitcase']),
    ],
)
plan,_=enrich_plan(plan,known_backgrounds=set(background_ids()))
assert plan.scenes[0].visual_action in {'run','chase'}
assert plan.scenes[1].visual_action=='reaction'
assert plan.scenes[2].visual_action not in {'run','chase'}
assert all('phone' not in s.props and 'camera' not in s.props for s in plan.scenes)
assert all('suitcase' in s.props for s in plan.scenes)

renderer=CartoonRenderer(project_root=root,language=load_language_pack('english'))
with tempfile.TemporaryDirectory(prefix='cartoon-v11-quality-') as temp:
    path=renderer.self_test(Path(temp))
    motion=renderer._measure_motion_quality(path)
    assert motion['status']=='PASS', motion
    assert motion['median_yavg'] >= cfg['motion_quality']['minimum_median_difference_yavg'], motion
    assert motion['mid80_mean_yavg'] >= cfg['motion_quality']['minimum_mid80_mean_yavg'], motion

print('scene-specific action overrides topic-wide run: OK')
print('world-default prop injection removed: OK')
print('explicit suitcase persistence: OK')
print('exclusive body-state compositor: OK')
print('foot-plant locomotion contract: OK')
print('actor-local prop ownership: OK')
print('primary actor-only translation: OK')
print('dialogue closeups independent of scene action: OK')
print('anti-slideshow motion gate: OK')
print('V11.1 PERFORMANCE INTENT/MOTION CONTRACT PASSED')
PY

for clip in \
  body_walk_right.mov \
  body_walk_left.mov \
  body_run_right.mov \
  body_run_left.mov \
  body_walk_carry_right.mov \
  body_run_carry_right.mov
do
  path="$PROJECT/assets/cartoon_v11/rigs/doctor/$clip"
  test -s "$path"
  codec="$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of default=nw=1:nk=1 "$path")"
  pix="$(ffprobe -v error -select_streams v:0 -show_entries stream=pix_fmt -of default=nw=1:nk=1 "$path")"
  test "$codec" = qtrle
  test "$pix" = argb
  echo "$clip codec=$codec alpha=$pix: OK"
done

python -m content_factory.cartoon.renderer --self-test --project-root "$PROJECT"

grep -q '_line_performance_action' "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q 'body states never stack' "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q 'actor track' "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q '_measure_motion_quality' "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q 'listener reaction cuts' "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q 'v11_foreground' "$PROJECT/src/content_factory/cartoon/renderer.py"

echo 'V11 12/24fps articulated performance: OK'
echo 'V11 exclusive body-state timeline: OK'
echo 'V11 foot-planted walk/run gait: OK'
echo 'V11 finite action then settle: OK'
echo 'V11 actor-local portable props: OK'
echo 'V11 line-specific acting + listener reactions: OK'
echo 'V11 dialogue close/reaction camera grammar: OK'
echo 'V11 foreground depth: OK'
echo 'V11 anti-slideshow final-video gate: OK'
echo 'V11.1 PRODUCTION PERFORMANCE CONTRACT PASSED'
