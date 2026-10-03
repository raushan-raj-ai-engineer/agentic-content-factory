from __future__ import annotations

import re
from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field, model_validator

ObjectKind = Literal[
    "text", "node", "agent", "model", "host", "client", "server", "tool", "resource",
    "prompt", "file", "folder", "document", "database", "vector_store", "browser", "terminal",
    "code", "function", "api", "array", "packet", "connector", "shield", "lock", "gate",
    "table", "user", "person", "place", "device", "app", "sensor", "badge", "balance",
    "equation", "graph", "chart", "number_line", "shape", "quantity",
    "vector", "atom", "molecule", "wave", "experiment",
    "book", "search_ui", "context_window", "answer_panel", "point_cloud", "theory_point",
]
Slot = Literal[
    "left_top", "left_mid", "left_bottom", "center_top", "center", "center_bottom",
    "right_top", "right_mid", "right_bottom", "wide_top", "wide_mid", "wide_bottom",
]
ActionKind = Literal[
    "reveal", "write", "connect", "move", "send", "return", "highlight", "transform",
    "select", "type_code", "step_code", "allow", "reject", "compare", "focus", "replace",
    "split", "merge", "scan", "stream",
]
LayoutKind = Literal[
    "freeform", "left_to_right", "radial", "split", "stack", "code_plus_state", "timeline",
    "browser_demo", "table_focus", "array_trace", "boundary", "analogy_map",
]
EnvironmentKind = Literal[
    "auto", "technical", "data_space", "code_lab", "browser_space", "document_space",
    "analogy_warm", "security_boundary", "science_lab", "clean_light",
]
CameraStyle = Literal["auto", "static", "guided", "follow", "focus", "cinematic"]
TransitionStyle = Literal["auto", "cut", "fade_through", "directional", "match_focus"]
MotionDensity = Literal["low", "medium", "high"]
LearningPhase = Literal[
    "hook", "explain", "flow", "example", "implementation", "verify", "recap", "cta"
]


class StudyVisualObject(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    kind: ObjectKind
    label: str = Field(min_length=1, max_length=64)
    slot: Slot
    detail: list[str] = Field(default_factory=list, max_length=6)


class StudyVisualBeat(BaseModel):
    cue: str = Field(min_length=1, max_length=120)
    action: ActionKind
    target: str
    source: str | None = None
    destination: str | None = None
    label: str | None = Field(default=None, max_length=64)
    weight: int = Field(default=1, ge=1, le=4)


class StudySceneStoryboard(BaseModel):
    scene_id: int = Field(gt=0)
    purpose: str = Field(min_length=3, max_length=180)
    layout: LayoutKind
    objects: list[StudyVisualObject] = Field(min_length=3, max_length=10)
    beats: list[StudyVisualBeat] = Field(min_length=4, max_length=12)
    reference_keywords: list[str] = Field(default_factory=list, max_length=8)
    teaching_pattern: Literal[
        "problem_solution", "progressive_flow", "worked_example", "retrieval_match",
        "compare_paths", "context_build", "verification", "recap",
        "concept_explain", "mechanism_flow",
    ] = "progressive_flow"
    interaction_prompt: str | None = Field(default=None, max_length=110)
    interaction_answer: str | None = Field(default=None, max_length=72)
    interaction_choices: list[str] = Field(default_factory=list, max_length=3)
    interaction_style: Literal["predict", "quick_check", "recall"] | None = None
    environment: EnvironmentKind = "auto"
    camera_style: CameraStyle = "auto"
    transition_style: TransitionStyle = "auto"
    motion_density: MotionDensity = "medium"
    learning_phase: LearningPhase = "explain"
    chapter_title: str = Field(default="", max_length=90)

    @model_validator(mode="after")
    def validate_refs(self):
        ids = [obj.id for obj in self.objects]
        if len(ids) != len(set(ids)):
            raise ValueError("Storyboard object IDs must be unique")
        known = set(ids)
        for beat in self.beats:
            for ref in (beat.target, beat.source, beat.destination):
                if ref and ref not in known:
                    raise ValueError(f"Unknown storyboard object reference: {ref}")
        return self

    @property
    def signature(self) -> str:
        kinds = ",".join(obj.kind for obj in self.objects)
        actions = ",".join(beat.action for beat in self.beats)
        return (
            f"{self.learning_phase}|{self.layout}|{self.environment}|{self.camera_style}|"
            f"{kinds}|{actions}"
        )


class StudyStoryboardBatch(BaseModel):
    scenes: list[StudySceneStoryboard] = Field(min_length=1, max_length=12)


_GENERIC = {
    "context", "introduction", "core idea", "mechanism", "takeaway", "topic", "example",
    "thing", "stuff", "this", "that", "finally", "today", "learn", "understand",
    "narration", "visualize", "visual", "scene", "instruction", "concrete visual",
    "narration text", "narration concept",
}


def clean_storyboard(storyboard: StudySceneStoryboard, *, title: str, topic: str) -> StudySceneStoryboard:
    """Sanitize LLM storyboards and prevent the v0.4.x generic-label failure mode."""
    title_norm = _norm(title)
    topic_norm = _norm(topic)
    objects: list[StudyVisualObject] = []
    seen_labels: set[str] = set()
    for obj in storyboard.objects:
        label = re.sub(r"\s+", " ", obj.label).strip(" .,:;—-_")
        norm = _norm(label)
        if not label or norm in _GENERIC or norm in {title_norm, topic_norm}:
            continue
        # Mobile-first teaching labels: one short concept, not a sentence.
        # Never add an ellipsis: a visibly cut label looks like broken UI.
        words = label.split()
        if len(words) > 5:
            label = " ".join(words[:5])
        if len(label) > 48:
            compact: list[str] = []
            for word in label.split():
                if compact and len(" ".join([*compact, word])) > 48:
                    break
                compact.append(word)
            label = " ".join(compact) or label[:48].rstrip()
        if norm in seen_labels:
            continue
        seen_labels.add(norm)
        objects.append(obj.model_copy(update={"label": label}))

    # Keep referenced object IDs; if sanitizing removed something, retain it with a useful compact label.
    needed = {b.target for b in storyboard.beats}
    needed |= {b.source for b in storyboard.beats if b.source}
    needed |= {b.destination for b in storyboard.beats if b.destination}
    present = {o.id for o in objects}
    by_id = {o.id: o for o in storyboard.objects}
    for missing in sorted(needed - present):
        original = by_id[missing]
        fallback = original.kind.replace("_", " ").title()
        objects.append(original.model_copy(update={"label": fallback}))

    if len(objects) < 3:
        objects = list(storyboard.objects[:3])

    # Avoid accidental object overlap from repeated slots. Keep wide slots unique too.
    slot_order = [
        "left_top", "center_top", "right_top", "left_mid", "center", "right_mid",
        "left_bottom", "center_bottom", "right_bottom", "wide_top", "wide_mid", "wide_bottom",
    ]
    used: set[str] = set()
    adjusted: list[StudyVisualObject] = []
    for obj in objects[:10]:
        slot = obj.slot
        if slot in used:
            slot = next((candidate for candidate in slot_order if candidate not in used), slot)
        used.add(slot)
        adjusted.append(obj.model_copy(update={"slot": slot}))

    return storyboard.model_copy(update={"objects": adjusted})


def diversity_report(storyboards: list[StudySceneStoryboard]) -> dict[str, object]:
    if not storyboards:
        return {
            "unique_ratio": 1.0, "max_adjacent_repeat": 0, "max_layout_run": 0,
            "high_similarity_pairs": [], "signatures": [],
        }
    sigs = [s.signature for s in storyboards]
    unique_ratio = len(set(sigs)) / len(sigs)
    max_run = 1
    run = 1
    max_layout_run = 1
    layout_run = 1
    high_similarity_pairs: list[list[int]] = []
    for prev, cur in zip(storyboards, storyboards[1:]):
        run = run + 1 if cur.signature == prev.signature else 1
        max_run = max(max_run, run)
        layout_run = layout_run + 1 if cur.layout == prev.layout else 1
        max_layout_run = max(max_layout_run, layout_run)

        prev_kinds = {o.kind for o in prev.objects}
        cur_kinds = {o.kind for o in cur.objects}
        prev_actions = {b.action for b in prev.beats}
        cur_actions = {b.action for b in cur.beats}
        kind_union = prev_kinds | cur_kinds
        action_union = prev_actions | cur_actions
        kind_similarity = len(prev_kinds & cur_kinds) / max(1, len(kind_union))
        action_similarity = len(prev_actions & cur_actions) / max(1, len(action_union))
        same_layout = 1.0 if prev.layout == cur.layout else 0.0
        similarity = 0.45 * kind_similarity + 0.35 * action_similarity + 0.20 * same_layout
        if similarity >= 0.78:
            high_similarity_pairs.append([prev.scene_id, cur.scene_id])

    return {
        "unique_ratio": round(unique_ratio, 3),
        "max_adjacent_repeat": max_run,
        "max_layout_run": max_layout_run,
        "high_similarity_pairs": high_similarity_pairs,
        "signatures": sigs,
        "layout_counts": dict(Counter(s.layout for s in storyboards)),
        "teaching_pattern_counts": dict(Counter(s.teaching_pattern for s in storyboards)),
    }


REAL_WORLD_KINDS = {"person", "place", "device", "app", "sensor", "file", "folder", "document", "book", "user"}
TECHNICAL_KINDS = {
    "agent", "model", "host", "client", "server", "tool", "resource", "prompt",
    "database", "vector_store", "browser", "terminal", "code", "function", "api",
    "array", "packet", "connector", "shield", "lock", "gate", "table",
    "equation", "graph", "chart", "number_line", "shape", "quantity", "vector",
    "atom", "molecule", "wave", "experiment",
    "book", "search_ui", "context_window", "answer_panel", "point_cloud",
}
GENERIC_KINDS = {"text", "node", "badge", "balance"}


def storyboard_quality_report(storyboards: list[StudySceneStoryboard]) -> dict[str, object]:
    """Semantic quality report for study animation planning.

    Motion alone is not a teaching-quality signal. This report checks whether
    storyboards use concrete domain objects and whether specialized layouts
    contain the semantic actions they are supposed to teach.
    """
    if not storyboards:
        return {
            "score": 100,
            "generic_object_ratio": 0.0,
            "specialized_scene_pass_ratio": 1.0,
            "dynamic_scene_ratio": 1.0,
            "placeholder_label_ratio": 0.0,
            "overloaded_scene_ratio": 0.0,
            "layout_dominance_ratio": 0.0,
            "raw_layout_dominance_ratio": 0.0,
            "high_similarity_pair_ratio": 0.0,
            "issues": [],
        }

    total_objects = sum(len(s.objects) for s in storyboards) or 1
    generic_objects = sum(
        1 for scene in storyboards for obj in scene.objects if obj.kind in GENERIC_KINDS
    )
    issues: list[str] = []
    specialized_total = 0
    specialized_pass = 0
    dynamic_total = 0
    dynamic_pass = 0
    state_actions = {
        "move", "send", "return", "transform", "replace", "step_code", "allow",
        "reject", "select", "compare", "split", "merge", "scan", "stream",
    }

    for scene in storyboards:
        kinds = {o.kind for o in scene.objects}
        actions = {b.action for b in scene.beats}
        passed = True
        specialized = False

        if scene.layout == "analogy_map":
            specialized = True
            passed = bool(kinds & REAL_WORLD_KINDS) and bool(kinds & TECHNICAL_KINDS) and bool(actions & {"transform", "replace"})
            if not passed:
                issues.append(f"scene {scene.scene_id}: analogy lacks real-world→technical transformation")
        elif scene.layout == "code_plus_state":
            specialized = True
            passed = "code" in kinds and bool(actions & {"type_code", "step_code"})
            if not passed:
                issues.append(f"scene {scene.scene_id}: code scene lacks executable code progression")
        elif scene.layout == "boundary":
            specialized = True
            passed = bool(kinds & {"gate", "shield", "lock"}) and bool(actions & {"allow", "reject"})
            if not passed:
                issues.append(f"scene {scene.scene_id}: boundary scene lacks allow/reject behavior")
        elif "packet" in kinds and scene.layout in {"left_to_right", "split", "freeform"}:
            specialized = True
            passed = bool(actions & {"send", "return", "move"})
            if not passed:
                issues.append(f"scene {scene.scene_id}: protocol/data scene lacks state movement")

        if specialized:
            specialized_total += 1
            specialized_pass += int(passed)

        dynamic_total += 1
        has_state_change = bool(actions & state_actions)
        dynamic_pass += int(has_state_change)
        if not has_state_change:
            issues.append(f"scene {scene.scene_id}: no meaningful state-changing animation beat")

    generic_ratio = generic_objects / total_objects
    specialized_ratio = specialized_pass / specialized_total if specialized_total else 1.0
    dynamic_ratio = dynamic_pass / dynamic_total if dynamic_total else 1.0

    placeholder_re = re.compile(r"^(?:part|section|chapter|input|process|result|verify|current task|incoming request)(?:\s*[-—:]?\s*\d+)?$", re.I)
    placeholder_labels = [
        obj.label for scene in storyboards for obj in scene.objects
        if placeholder_re.match(obj.label.strip())
    ]
    placeholder_ratio = len(placeholder_labels) / total_objects
    overloaded_ratio = sum(1 for scene in storyboards if len(scene.objects) > 5) / max(1, len(storyboards))
    layout_counts = Counter(scene.layout for scene in storyboards)
    raw_layout_dominance = max(layout_counts.values()) / max(1, len(storyboards))

    # v1.2.1: Beginner-first pedagogy deliberately gives EXPLAIN scenes a
    # consistent theory-board grammar and FLOW scenes a consistent process
    # grammar. Counting those mandated layouts as generic repetition creates a
    # false failure exactly when the lesson is following the intended
    # EXPLAIN -> FLOW contract. Diversity enforcement therefore measures layout
    # dominance only across flexible phases where the director is free to vary
    # composition (hook/example/implementation/verify/recap/cta). Raw dominance
    # is still reported for diagnostics. Adjacent semantic similarity remains a
    # lesson-wide signal, so genuinely cloned scenes are still caught.
    flexible_phases = {"hook", "example", "implementation", "verify", "recap", "cta"}
    flexible_scenes = [s for s in storyboards if s.learning_phase in flexible_phases]
    if len(flexible_scenes) >= 4:
        flexible_counts = Counter(scene.layout for scene in flexible_scenes)
        layout_dominance = max(flexible_counts.values()) / len(flexible_scenes)
    else:
        layout_dominance = 0.0

    diversity = diversity_report(storyboards)
    raw_high_similarity_ratio = len(diversity.get("high_similarity_pairs", [])) / max(1, len(storyboards) - 1)
    # Diversity statistics are meaningful across a lesson, not for a one/two-scene
    # unit test or a deliberately short sample. Do not penalize tiny sets.
    high_similarity_ratio = raw_high_similarity_ratio if len(storyboards) >= 4 else 0.0

    score = round(max(0.0, 100.0
        - generic_ratio * 24.0
        - (1.0 - specialized_ratio) * 38.0
        - (1.0 - dynamic_ratio) * 22.0
        - placeholder_ratio * 45.0
        - overloaded_ratio * 18.0
        - max(0.0, layout_dominance - 0.34) * 55.0
        - high_similarity_ratio * 30.0
    ), 1)
    if generic_ratio > 0.40:
        issues.append(f"generic object ratio too high: {generic_ratio:.2f}")
    if placeholder_ratio > 0.08:
        issues.append(f"placeholder label ratio too high: {placeholder_ratio:.2f}")
    if overloaded_ratio > 0.30:
        issues.append(f"too many scenes use >5 simultaneous objects: {overloaded_ratio:.2f}")
    if layout_dominance > 0.38:
        issues.append(f"one layout dominates the lesson: {layout_dominance:.2f}")
    if high_similarity_ratio > 0.25:
        issues.append(f"adjacent semantic scene similarity too high: {high_similarity_ratio:.2f}")

    return {
        "score": score,
        "generic_object_ratio": round(generic_ratio, 3),
        "specialized_scene_pass_ratio": round(specialized_ratio, 3),
        "dynamic_scene_ratio": round(dynamic_ratio, 3),
        "placeholder_label_ratio": round(placeholder_ratio, 3),
        "overloaded_scene_ratio": round(overloaded_ratio, 3),
        "layout_dominance_ratio": round(layout_dominance, 3),
        "raw_layout_dominance_ratio": round(raw_layout_dominance if len(storyboards) >= 4 else 0.0, 3),
        "high_similarity_pair_ratio": round(high_similarity_ratio, 3),
        "issues": issues,
    }


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()
