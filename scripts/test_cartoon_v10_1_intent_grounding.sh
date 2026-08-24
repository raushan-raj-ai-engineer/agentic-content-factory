#!/usr/bin/env bash
set -euo pipefail
PROJECT="${1:-/Users/maa/agentic-content-factory}"
cd "$PROJECT"
source .venv/bin/activate
export PYTHONPATH="$PROJECT/src${PYTHONPATH:+:$PYTHONPATH}"

python - <<'PY'
from content_factory.cartoon.capabilities import (
    infer_props, resolve_action_families, resolve_topic_capabilities,
    resolve_topic_world_sequence,
)
from content_factory.cartoon.characters import character_registry
from content_factory.cartoon.monetization import _contains_any
from content_factory.cartoon.router import resolve_story_profile
from content_factory.cartoon.story_planner import CartoonStoryPlanner

TOPIC="Doctor runs through an airport carrying a suitcase"

cap=resolve_topic_capabilities(TOPIC)
assert cap["world"]=="airport", cap
assert cap["matched_world_anchors"], cap
assert cap["cast"][0]=="doctor", cap

actions=resolve_action_families(TOPIC)
assert actions[0]=="run", actions
assert "carry" in actions, actions
assert "suitcase" in infer_props(TOPIC)

profile=resolve_story_profile(topic=TOPIC,language_code="english")
assert profile["preferred_cast"][0]=="doctor", profile
assert profile["locations"]==["airport"], profile["locations"]
assert profile["topic_actions"][0]=="run", profile
assert "carry" in profile["topic_actions"], profile
assert "suitcase" in profile["topic_props"], profile

cast=[x for x in profile["preferred_cast"] if x in character_registry()][:5]
briefs=CartoonStoryPlanner._build_scene_briefs(
    topic=TOPIC,cast_ids=cast,scene_target=6,premise_lock=profile
)
assert all(b.location_id=="airport" for b in briefs), [b.location_id for b in briefs]
combined=" ".join(b.summary for b in briefs).lower()
assert "family or society" not in combined
assert "career" not in combined
assert "airport" in combined
assert "suitcase" in combined

assert _contains_any("Something happens at the airport.",["meth"])==[]
assert _contains_any("The story explicitly mentions meth.",["meth"])==["meth"]

multi=resolve_topic_world_sequence(
    "A doctor leaves the hospital, takes a train, then reaches the airport."
)
assert multi==["hospital","railway","airport"], multi

print("exact topic -> AIRPORT, not hospital: OK")
print("doctor auto cast first: OK")
print("run + carry composite intent: OK")
print("suitcase story prop persistence: OK")
print("single-world scene briefs remain airport: OK")
print("generic family/career grammar removed: OK")
print("multi-world ordering: OK")
print("monetization substring false-positive removed: OK")
print("CARTOON INTENT GROUNDING V10.1 TESTS PASSED")
PY

grep -q 'auto-topic' "$PROJECT/src/content_factory/cartoon/cli.py"
grep -q 'cast_source=' "$PROJECT/src/content_factory/cartoon/cli.py"
grep -q 'cast=planner_cast' "$PROJECT/src/content_factory/cartoon/cli.py"
grep -q '\[CARTOON RENDER WARNING\]' "$PROJECT/src/content_factory/cartoon/renderer.py"
grep -q 'hits=' "$PROJECT/src/content_factory/cartoon/monetization.py"

echo "auto topic cast reaches planner: OK"
echo "renderer degradation reasons visible: OK"
echo "monetization exact-hit logs visible: OK"
echo "V10.1.1 INTENT-GROUNDED QUALITY CONTRACT PASSED"
