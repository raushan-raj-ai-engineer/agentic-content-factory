#!/usr/bin/env bash
set -euo pipefail
PROJECT="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$PROJECT"
source .venv/bin/activate
export PYTHONPATH="$PROJECT/src${PYTHONPATH:+:$PYTHONPATH}"
python - <<'PY'
from content_factory.cartoon.language import load_language_pack
from content_factory.cartoon.story_planner import CartoonStoryPlanner

exact_topic = (
    "Guddu ke bakra mobile leke bhaag gel — ghar ke aangan se bazaar, chai dukan, "
    "school ground aur bus stand tak sab log bakra ke pakde la daudait hai, aur ant me "
    "bakra mobile se selfie le leta hai."
)
cast = ["teacher", "guest_child", "guddu", "bittu"]
lang = load_language_pack("magahi")

# Exact regression from the user run: full deterministic fallback must construct.
plan = CartoonStoryPlanner.create_fallback_plan(
    topic=exact_topic,
    language=lang,
    target_minutes=2,
    cast=cast,
)
assert len(plan.scenes) == 6, len(plan.scenes)
assert 1 <= len(plan.title) <= 120
assert 1 <= len(plan.premise) <= 800

# Direct brief boundary: every scene summary must satisfy the Pydantic max_length=500.
premise = CartoonStoryPlanner._resolve_story_premise(
    topic=exact_topic,
    language_code="magahi",
)
briefs = CartoonStoryPlanner._build_scene_briefs(
    topic=exact_topic,
    cast_ids=cast,
    scene_target=9,
    premise_lock=premise,
)
assert briefs and all(1 <= len(b.summary) <= 500 for b in briefs)
assert all(1 <= len(b.comedy_goal) <= 300 for b in briefs)

# Arbitrary very long multilingual/Unicode input cannot crash either path.
long_topic = (exact_topic + " मगही मजेदार कहानी 🌟 ") * 30
premise2 = CartoonStoryPlanner._resolve_story_premise(
    topic=long_topic,
    language_code="magahi",
)
briefs2 = CartoonStoryPlanner._build_scene_briefs(
    topic=long_topic,
    cast_ids=cast,
    scene_target=9,
    premise_lock=premise2,
)
assert all(len(b.summary) <= 500 for b in briefs2)
plan2 = CartoonStoryPlanner.create_fallback_plan(
    topic=long_topic,
    language=lang,
    target_minutes=2,
    cast=cast,
)
assert plan2.scenes
assert len(plan2.title) <= 120
assert len(plan2.premise) <= 800

print("exact_magahi_long_topic_fallback=OK")
print("episode_title_max_120=OK")
print("episode_premise_max_800=OK")
print("scene_summary_max_500=OK")
print("comedy_goal_max_300=OK")
print("arbitrary_unicode_long_topic=OK")
print("normal_and_recovery_brief_builder=OK")
print("CARTOON LONG-TOPIC PLANNER V11.3.2 TESTS PASSED")
PY
