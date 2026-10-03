from __future__ import annotations

import math
import re
from dataclasses import asdict
from typing import Any

PEDAGOGY_VERSION = "sme-study-v4-beginner"

# Study videos need enough time for the viewer to inspect code/diagrams while
# listening. These are intentionally slower than entertainment/news narration.
TARGET_WPM_BY_STAGE = {
    "hook": 154,
    "theory": 142,
    "concept": 145,
    "trace": 146,
    "decision": 145,
    "verify": 146,
    "code": 142,
    "complexity": 146,
    "edge-cases": 145,
    "practice": 148,
    "recap": 150,
    "explain": 148,
}

TRAILING_PAUSE_BY_STAGE = {
    "hook": 0.35,
    "theory": 0.55,
    "concept": 0.50,
    "trace": 0.45,
    "decision": 0.45,
    "verify": 0.50,
    "code": 0.55,
    "complexity": 0.45,
    "edge-cases": 0.45,
    "practice": 0.55,
    "recap": 0.45,
    "explain": 0.40,
}


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text, flags=re.UNICODE))


def target_wpm(stage: str | None) -> int:
    return TARGET_WPM_BY_STAGE.get((stage or "explain").strip().lower(), 148)


def trailing_pause(stage: str | None) -> float:
    return TRAILING_PAUSE_BY_STAGE.get((stage or "explain").strip().lower(), 0.40)


def adaptive_tempo(*, text: str, raw_seconds: float, stage: str | None) -> float:
    """Return an FFmpeg atempo value that targets a study-friendly speaking rate.

    We only slow down narration here. If a voice is naturally slower than the
    target, it is left alone rather than artificially speeding it up.
    """
    if raw_seconds <= 0:
        return 1.0
    current_wpm = word_count(text) / raw_seconds * 60.0
    if current_wpm <= 0:
        return 1.0
    desired = target_wpm(stage)
    tempo = desired / current_wpm
    return round(max(0.78, min(1.0, tempo)), 4)


def estimated_read_seconds(text: str, stage: str | None) -> float:
    words = max(1, word_count(text))
    return words / target_wpm(stage) * 60.0 + trailing_pause(stage)


def sme_review(lesson: Any) -> dict[str, Any]:
    """Deterministic pedagogy checklist for generated study lessons.

    This is not a factual oracle. It verifies that the deterministic lesson
    builder includes the instructional components expected from a subject-
    matter-expert style explainer.
    """
    scenes = [asdict(scene) for scene in lesson.scenes]
    stages = [str(scene.get("stage") or "") for scene in scenes]
    titles = [str(scene.get("title") or "").lower() for scene in scenes]

    checks = {
        "hook_present": bool(scenes and stages[0] == "hook"),
        "beginner_theory_present": "theory" in stages,
        "theory_before_trace": "theory" in stages and any(x in stages for x in ("trace", "decision")) and stages.index("theory") < min(stages.index(x) for x in ("trace", "decision") if x in stages),
        "concept_before_code": "concept" in stages and "code" in stages and stages.index("concept") < stages.index("code"),
        "worked_trace_present": any(stage in {"trace", "decision", "verify"} for stage in stages),
        "implementation_present": "code" in stages,
        "code_explains_trace_mapping": any(
            scene.get("stage") == "code"
            and "connect" in str(scene.get("narration") or "").lower()
            for scene in scenes
        ),
        "concrete_edge_examples_present": any(
            scene.get("stage") == "edge-cases"
            and any(token in str(scene.get("narration") or "") for token in ("[", "'", '"', "returns", "becomes"))
            for scene in scenes
        ),
        "complexity_present": "complexity" in stages or any("time and space" in title for title in titles),
        "edge_cases_present": "edge-cases" in stages or any("edge case" in title for title in titles),
        "practice_present": "practice" in stages,
        "visual_cues_present": any(scene.get("pointers") or scene.get("comparison") or scene.get("callout") for scene in scenes),
        "narration_chunks_readable": all(word_count(scene.get("narration", "")) <= 85 for scene in scenes),
    }
    passed = all(checks.values())
    return {
        "version": PEDAGOGY_VERSION,
        "passed": passed,
        "checks": checks,
        "target_wpm_by_stage": TARGET_WPM_BY_STAGE,
        "design_contract": [
            "Hook with a concrete learner problem",
            "Give a beginner-friendly definition and prerequisite before tracing",
            "Use a simple analogy or mental model when it genuinely clarifies the idea",
            "Explain the mental model before implementation details",
            "Show state changes visually instead of narrating a static slide",
            "Connect variables and decisions in the trace to exact code behavior",
            "Explain time/space complexity from the mechanism, not memorization",
            "Cover edge cases with concrete examples and the problem contract",
            "End with a prediction/practice prompt",
        ],
    }


def readable_duration(seconds: float) -> float:
    """Round render durations without allowing near-zero scenes."""
    return max(1.2, math.ceil(seconds * 20.0) / 20.0)
