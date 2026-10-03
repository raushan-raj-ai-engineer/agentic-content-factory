#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

cd "$PROJECT"
source .venv/bin/activate

python - <<'PY'
from types import SimpleNamespace

from content_factory.research.topic_quality import (
    evidence_semantic_coherence,
    is_calendar_only_topic,
    topic_quality_factor,
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

# ------------------------------------------------------------------
# Topic specificity.
# ------------------------------------------------------------------
assert is_calendar_only_topic(
    "21 De Agosto"
)
assert is_calendar_only_topic(
    "August 21 2026"
)
assert is_calendar_only_topic(
    "21 अगस्त 2026"
)
assert not is_calendar_only_topic(
    "Eclipse Lunar De Agosto De 2026"
)
assert not is_calendar_only_topic(
    "August 21 earthquake"
)

assert ResearchPlannerAgent._topic_clarity(
    "21 De Agosto"
) <= 25

assert TrendResearchAgent._topic_clarity(
    "21 De Agosto"
) <= 25

print("Calendar-only topic rejection: OK")

# ------------------------------------------------------------------
# Semantic coherence.
# ------------------------------------------------------------------
mixed = [
    "SANTO DO DIA - 21 DE AGOSTO",
    "Noticiero en vivo 21 de agosto",
    "Oração do dia 21 de agosto",
    "Radio matinal 21 de agosto",
]

factor, coherence = topic_quality_factor(
    "21 De Agosto",
    mixed,
)

assert factor <= 0.20
assert coherence < 0.60

print(
    f"Date evidence coherence guard: OK "
    f"(coherence={coherence:.2f}, factor={factor:.2f})"
)

# ------------------------------------------------------------------
# Domain hijack guard.
# ------------------------------------------------------------------
date_domain = ContentProductionAgent._resolve_domain_classification(
    identity_context=(
        "21 De Agosto current public reports educational explainer"
    ),
    full_context=(
        "21 De Agosto current public reports. "
        "One section mentions LPL esports gaming and LCK matches."
    ),
    has_factual_evidence=True,
)

assert date_domain.domain == "general", date_domain.to_dict()

game_domain = ContentProductionAgent._resolve_domain_classification(
    identity_context=(
        "Minecraft gameplay update video game"
    ),
    full_context=(
        "Minecraft gameplay update video game console"
    ),
    has_factual_evidence=True,
)

assert game_domain.domain == "gaming", game_domain.to_dict()

print("Body-only gaming domain hijack guard: OK")

assert ContentProductionAgent._use_natural_photo(
    family="factual_editorial",
    domain="general",
    scene_index=1,
    block_kind="hook",
)

print("General factual natural-photo anchors: OK")

# ------------------------------------------------------------------
# Script performance / duration reconciliation.
# ------------------------------------------------------------------
assert not ScriptWriterAgent._should_attempt_length_repair(
    word_count=450,
    min_words=901,
    max_words=1213,
)

assert ScriptWriterAgent._should_attempt_length_repair(
    word_count=800,
    min_words=901,
    max_words=1213,
)

assert ScriptWriterAgent._estimated_duration_minutes(
    450
) == 3

print("Severe script-shortfall duplicate rewrite guard: OK")
print("Deterministic script duration reconciliation: OK")

print()
print("TOPIC COHERENCE QUALITY V8.5 TESTS PASSED")
PY
