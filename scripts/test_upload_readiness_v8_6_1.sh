#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-/Users/maa/agentic-content-factory}"

cd "$PROJECT"
source .venv/bin/activate

python - <<'PY'
from content_factory.research.topic_quality import (
    is_calendar_only_topic,
)
from content_factory.agents.research_planner import (
    ResearchPlannerAgent,
)
from content_factory.agents.trend_researcher import (
    TrendResearchAgent,
)
from content_factory.agents.content_producer import (
    ContentProductionAgent,
)
from content_factory.agents.script_writer import (
    ScriptWriterAgent,
)
from content_factory.models.content import (
    VisualScene,
)
from content_factory.visual.semantic_router import (
    decide_visual_route,
)

# V8.5 cumulative checks.
assert is_calendar_only_topic("21 De Agosto")
assert not is_calendar_only_topic(
    "Eclipse Lunar De Agosto De 2026"
)
assert ResearchPlannerAgent._topic_clarity(
    "21 De Agosto"
) <= 25
assert TrendResearchAgent._topic_clarity(
    "21 De Agosto"
) <= 25
assert not ScriptWriterAgent._should_attempt_length_repair(
    word_count=450,
    min_words=901,
    max_words=1213,
)

print("V8.5 topic/script protections: OK")

# Exact old upload-risk failure mode: nine identical gaming key-art scenes.
scenes = [
    VisualScene(
        id=i,
        title=f"Scene {i}",
        description="test",
        visual_type="gaming_key_art",
        subject="test",
        key_elements=["test"],
        composition="test",
        style="test",
        avoid=[],
        voice_segment_id=i,
    )
    for i in range(1, 10)
]

ContentProductionAgent._ensure_upload_ready_visual_variety(
    visual_scenes=scenes,
    domain="gaming",
    family="creative",
)

types = {
    scene.visual_type
    for scene in scenes
}

assert len(types) >= 3, types
assert "gaming_key_art" in types

print(
    "9x same-treatment repair: OK -> "
    + ", ".join(sorted(types))
)

# Structured scenes must not be forced through diffusion by gaming context.
decision = decide_visual_route(
    title="Game update timeline",
    description="Patch history",
    prompt="timeline explainer",
    visual_type="timeline_scene",
    context_domain="gaming",
)
assert decision.route == "editorial", decision
print("Gaming timeline -> editorial: OK")

decision = decide_visual_route(
    title="Game hero",
    description="premium hero",
    prompt="premium game art",
    visual_type="gaming_key_art",
    context_domain="gaming",
)
assert decision.route == "diffusion", decision
print("Gaming hero -> premium diffusion: OK")

decision = decide_visual_route(
    title="General explainer",
    description="summary",
    prompt="clean summary",
    visual_type="editorial_summary",
    context_domain="general",
)
assert decision.route == "editorial", decision
print("General summary -> editorial: OK")

print()
print("UPLOAD READINESS V8.6.1 TESTS PASSED")
PY
