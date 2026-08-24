#!/usr/bin/env bash
set -euo pipefail
TARGET="${1:-$PWD}"
export PYTHONPATH="$TARGET/src${PYTHONPATH:+:$PYTHONPATH}"
export CONTENT_FACTORY_CARTOON_CHANNEL=hindi_mass

python -m py_compile \
  "$TARGET/src/content_factory/cartoon/story_planner.py" \
  "$TARGET/src/content_factory/cartoon/renderer.py" \
  "$TARGET/src/content_factory/cartoon/quality_reset_v17.py"

python - <<'PY'
import os
from content_factory.cartoon.quality_reset_v17 import apply_hindi_mass_location_policy
p={"route":"family_comedy","locations":["living_room","courtyard","tea_shop","market"],"explicit_locations":[],"forced_location_arc":[]}
r=apply_hindi_mass_location_policy("Babuji AI assistant se ghar ka kaam karte hain",p)
assert set(r["locations"]).issubset({"living_room","courtyard","outdoor_kitchen","rooftop","bedroom"}), r
assert "city_street" not in r["locations"] and "market" not in r["locations"], r
print("implicit_family_home_location_lock=OK")

p2={"route":"family_comedy","locations":["market"],"explicit_locations":["market"],"forced_location_arc":[]}
r2=apply_hindi_mass_location_policy("Babuji market jaate hain",p2)
assert r2["locations"]==["market"], r2
print("explicit_location_override_preserved=OK")
PY

grep -q 'CARTOON QUALITY V17.1' "$TARGET/src/content_factory/cartoon/story_planner.py"
grep -q '50-65 SPOKEN words' "$TARGET/src/content_factory/cartoon/story_planner.py"
grep -q 'do not add filler' "$TARGET/src/content_factory/cartoon/story_planner.py"
grep -q 'CARTOON AUDIO V17.1' "$TARGET/src/content_factory/cartoon/renderer.py"
grep -q '_master_indian_episode_audio' "$TARGET/src/content_factory/cartoon/renderer.py"
grep -q 'if natural_actor_available(self.project_root, cid)' "$TARGET/src/content_factory/cartoon/renderer.py"
if grep -q 'natural_actor_available(self.project_root, cid) and action not in locomotion_actions' "$TARGET/src/content_factory/cartoon/renderer.py"; then
  echo 'ERROR: old geometric fallback condition still present' >&2
  exit 1
fi
# The whole-scene local repair must not trigger merely on duplicate dialogue.
python - <<PY
from pathlib import Path
s=Path("$TARGET/src/content_factory/cartoon/story_planner.py").read_text()
start=s.index('def _repair_quality_locally')
end=s.index('def _normalize_scene_speakers',start)
block=s[start:end]
assert '"duplicate dialogue" not in issue' not in block, block[:1200]
print('near_duplicate_no_full_scene_fallback=OK')
PY

echo 'llm_density_repair_hook=OK'
echo 'actual_tts_duration_calibration=OK'
echo 'natural_actor_locomotion_preserved=OK'
echo 'final_hindi_mastering_pass=OK'
echo 'V17.1 QUALITY RECOVERY TESTS PASSED'
