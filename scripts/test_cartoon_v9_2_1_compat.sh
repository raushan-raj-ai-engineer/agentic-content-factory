#!/usr/bin/env bash
set -euo pipefail
PROJECT="${1:-/Users/maa/agentic-content-factory}"
cd "$PROJECT"
source .venv/bin/activate
export PYTHONPATH="$PROJECT/src${PYTHONPATH:+:$PYTHONPATH}"
python - <<'PY2'
from content_factory.cartoon.router import resolve_story_profile
from content_factory.cartoon.story_planner import CartoonStoryPlanner
career=resolve_story_profile(topic="Indian parents vs career choice",language_code="hindi")
assert career["key"]=="game_designer"
for field in ("goal","safe_path","project","comparison"): assert career.get(field),field
assert "गेम डिजाइनर" in career["premise"]
assert "शर्मा जी" in career["premise"]
assert "मोबाइल गेम" in career["premise"]
assert len(CartoonStoryPlanner._premise_scene_directions(premise_lock=career,count=9))==9
minimal={"key":"game_designer","goal":"game designer"}
assert len(CartoonStoryPlanner._premise_scene_directions(premise_lock=minimal,count=9))==9
litti=resolve_story_profile(topic="Litti Chor Bandar",language_code="magahi")
assert litti["key"]=="litti_chor_bandar" and litti["route"]=="animal_comedy"
assert len(CartoonStoryPlanner._premise_scene_directions(premise_lock=litti,count=9))==9
generic=resolve_story_profile(topic="A completely unusual original cartoon premise",language_code="english")
assert generic["key"].startswith("route_")
assert len(CartoonStoryPlanner._premise_scene_directions(premise_lock=generic,count=9))==9
print("V9.0.6 career compatibility fields: OK")
print("incomplete special profile -> safe defaults: OK")
print("Litti route directions: OK")
print("generic route directions: OK")
print("career premise carries goal/project/comparison: OK")
print("UNIVERSAL ROUTER COMPAT V9.2.2 TESTS PASSED")
PY2
