#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-/Users/maa/agentic-content-factory}"

cd "$PROJECT"
source .venv/bin/activate

python - <<'PY'
import inspect
from types import SimpleNamespace

from content_factory.research.language_market import (
    target_locale,
)
from content_factory.agents.script_writer import (
    ScriptWriterAgent,
)
from content_factory.agents.packaging_optimizer import (
    PackagingOptimizerAgent,
)
from content_factory.voice.director import (
    VoiceDirector,
)
from content_factory.visual.domain_registry import (
    classify_domain,
)

assert target_locale(
    "pt",
    "BR",
) == "pt_BR"

assert target_locale(
    "es",
    "MX",
) == "es_MX"

assert target_locale(
    "ur",
    "PK",
) == "ur_PK"

assert target_locale(
    "bn",
    "BD",
) == "bn_BD"

print("Language + market -> locale mapping: OK")

state = SimpleNamespace(
    metadata={
        "target_language": "pt",
        "target_language_name": "Portuguese",
        "target_market_geo": "BR",
        "target_locale": "pt_BR",
    },
    strategy=SimpleNamespace(
        audience="Pessoas interessadas em novelas",
        topic="Quem Ama Cuida",
    ),
    topic="Quem Ama Cuida",
    script=SimpleNamespace(
        title="Quem Ama Cuida",
    ),
)

instruction = ScriptWriterAgent._language_instruction(
    state
)

assert "Portuguese" in instruction
assert "ALL viewer-facing" in instruction

print("Script target-language metadata priority: OK")

titles = PackagingOptimizerAgent._safe_titles(
    state
)

assert "O que" in titles[1]
assert all(
    "What We Know" not in title
    for title in titles
)

print("Localized safe packaging titles: OK")

director = VoiceDirector()

profile = director.profile_for(
    text="Bem-vindos ao vídeo.",
    audience=(
        "Target narration language: Portuguese. "
        "Target locale: pt_BR. "
        "Pessoas interessadas em novelas."
    ),
    topic="Quem Ama Cuida",
    segment_index=1,
    total_segments=10,
)

assert profile.locale == "pt_BR", profile

print("Voice Director explicit Portuguese target: OK")

ent = classify_domain(
    (
        "Quem Ama Cuida Brazilian telenovela "
        "capítulo episódio novela"
    )
)

assert ent.domain == "entertainment", ent.to_dict()

print("Telenovela -> entertainment domain: OK")

# Verify methods/signatures exist exactly as expected.
assert "_target_language_name" in dir(
    ScriptWriterAgent
)
assert "_target_language_name" in dir(
    PackagingOptimizerAgent
)

print("Localization helper methods: OK")
print()
print("LANGUAGE CONTINUITY V8.4.1 TESTS PASSED")
PY
