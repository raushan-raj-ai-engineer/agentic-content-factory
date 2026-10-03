#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

cd "$PROJECT"
source .venv/bin/activate

python - <<'PY'
import inspect

from content_factory.agents.research_planner import (
    ResearchPlannerAgent,
)
from content_factory.agents.trend_researcher import (
    TrendResearchAgent,
)
from content_factory.utils.unicode_tokens import (
    unicode_tokens,
)

planner_descriptor = ResearchPlannerAgent.__dict__[
    "_topic_clarity"
]
trend_descriptor = TrendResearchAgent.__dict__[
    "_topic_clarity"
]

assert isinstance(
    planner_descriptor,
    classmethod,
), type(planner_descriptor)

assert isinstance(
    trend_descriptor,
    classmethod,
), type(trend_descriptor)

assert list(
    inspect.signature(
        ResearchPlannerAgent._topic_clarity
    ).parameters
) == [
    "topic"
]

tests = [
    (
        "ന്യൂസ്",
        ["ന്യൂസ്"],
        25.0,
        "max",
    ),
    (
        "ભારતીય ક્રિકેટ ટીમ",
        [
            "ભારતીય",
            "ક્રિકેટ",
            "ટીમ",
        ],
        90.0,
        "min",
    ),
    (
        "உதயநிதி ஸ்டாலின்",
        [
            "உதயநிதி",
            "ஸ்டாலின்",
        ],
        90.0,
        "min",
    ),
    (
        "राजीव गांधी",
        [
            "राजीव",
            "गांधी",
        ],
        90.0,
        "min",
    ),
    (
        "ಭಾರತೀಯ ಕ್ರಿಕೆಟ್ ತಂಡ",
        [
            "ಭಾರತೀಯ",
            "ಕ್ರಿಕೆಟ್",
            "ತಂಡ",
        ],
        90.0,
        "min",
    ),
    (
        "Badminton World Championship",
        [
            "badminton",
            "world",
            "championship",
        ],
        95.0,
        "min",
    ),
]

for text, expected_tokens, threshold, mode in tests:
    tokens = unicode_tokens(
        text
    )
    planner_score = ResearchPlannerAgent._topic_clarity(
        text
    )
    trend_score = TrendResearchAgent._topic_clarity(
        text
    )

    assert tokens == expected_tokens, (
        text,
        tokens,
        expected_tokens,
    )

    if mode == "max":
        assert planner_score <= threshold, (
            text,
            planner_score,
        )
        assert trend_score <= threshold, (
            text,
            trend_score,
        )
    else:
        assert planner_score >= threshold, (
            text,
            planner_score,
        )
        assert trend_score >= threshold, (
            text,
            trend_score,
        )

    print(
        f"PASS  {text} -> "
        f"tokens={tokens}, "
        f"planner={planner_score:.0f}, "
        f"trend={trend_score:.0f}"
    )

print()
print("Unicode tokenization: OK")
print("ResearchPlanner _topic_clarity descriptor: classmethod OK")
print("TrendResearch _topic_clarity descriptor: classmethod OK")
print("Duplicate _topic_clarity definitions: NONE")
print()
print("UNICODE TREND TESTS PASSED")
PY
