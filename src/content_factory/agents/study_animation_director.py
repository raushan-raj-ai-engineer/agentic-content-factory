from __future__ import annotations

import json
import os
import re
from pathlib import Path

from content_factory.agents.base import Agent
from content_factory.llm.base import LLMProvider
from content_factory.modes import is_study_mode
from content_factory.orchestration.state import WorkflowState
from content_factory.utils.artifact_paths import artifact_subdir
from content_factory.visual.study_semantics import StudySemanticPlanner
from content_factory.visual.study_storyboard import (
    StudySceneStoryboard,
    StudyStoryboardBatch,
    StudyVisualBeat,
    StudyVisualObject,
    clean_storyboard,
    diversity_report,
    storyboard_quality_report,
)


class StudyAnimationDirectorAgent(Agent):
    """Create narration-driven animation storyboards before media generation.

    Unlike the v0.4.x archetype templates, this director plans concrete visual
    objects and timed semantic beats for each scene. The output is a finite DSL;
    no generated Python is ever executed.
    """

    BATCH_SIZE = 5

    def __init__(self, llm: LLMProvider, output_root: str = "artifacts") -> None:
        self._llm = llm
        self._output_root = Path(output_root)

    @property
    def name(self) -> str:
        return "Study Animation Director Agent"

    async def execute(self, state: WorkflowState) -> WorkflowState:
        if not is_study_mode(state):
            return state
        if state.production_plan is None:
            raise ValueError("Production plan is required before animation direction.")

        topic = state.topic or state.production_plan.title
        scenes = list(state.production_plan.visual_scenes)

        # A transient failure during script generation must not permanently bind
        # the quality-critical storyboard stage to a weaker local fallback.
        retry_primary = getattr(self._llm, "retry_primary", None)
        if callable(retry_primary):
            try:
                await retry_primary("study storyboard stage")
            except Exception as exc:
                print(f"[STUDY STORYBOARD] primary retry skipped ({exc.__class__.__name__})")

        storyboards: list[StudySceneStoryboard] = []
        recent_summaries: list[str] = []
        llm_rescued_scene_ids: list[int] = []
        deterministic_scene_ids: list[int] = []

        offset = 0
        last_batch_signature: tuple[str, int] | None = None
        while offset < len(scenes):
            provider_name = str(getattr(self._llm, "provider_name", "unknown"))
            if provider_name == "ollama":
                batch_size = max(1, min(2, int(os.getenv("STUDY_STORYBOARD_LOCAL_BATCH_SIZE", "1"))))
            else:
                # Smaller cloud batches are more reliable and still fast enough;
                # recompute each iteration so a runtime provider switch immediately
                # shrinks the next batch instead of sending 5-scene JSON to a 4B model.
                batch_size = max(2, min(4, int(os.getenv("STUDY_STORYBOARD_BATCH_SIZE", "3"))))
            signature = (provider_name, batch_size)
            if signature != last_batch_signature:
                print(
                    f"[STUDY STORYBOARD PERF] batch_size={batch_size} scenes={len(scenes)} "
                    f"provider={provider_name}"
                )
                last_batch_signature = signature
            batch_scenes = scenes[offset : offset + batch_size]
            prompt = self._prompt(topic, batch_scenes, recent_summaries[-4:])
            try:
                result = await self._llm.generate_structured(
                    prompt,
                    StudyStoryboardBatch,
                    system_prompt=(
                        "You are a senior educational motion designer and technical instructor. "
                        "Turn narration into visual teaching actions, not decorative motion."
                    ),
                    max_retries=1,
                    # Deep storyboards are more reliable through the shared
                    # provider-neutral JSON path than vendor-native schema subsets.
                    prefer_native=False,
                )
                mapped = {item.scene_id: item for item in result.scenes}
                planned: list[StudySceneStoryboard] = []
                for scene in batch_scenes:
                    item = mapped.get(scene.id)
                    if item is None:
                        raise ValueError(f"Missing storyboard for scene {scene.id}")
                    planned.append(self._finalize_storyboard(item, scene, topic))
            except Exception as exc:
                reason = str(exc).splitlines()[0][:180]
                print(
                    "[STUDY STORYBOARD] batch failed; attempting per-scene rescue: "
                    f"{type(exc).__name__}: {reason}"
                )
                planned = []
                for scene in batch_scenes:
                    try:
                        single = await self._llm.generate_structured(
                            self._prompt(topic, [scene], recent_summaries[-4:]),
                            StudyStoryboardBatch,
                            system_prompt=(
                                "You are a senior educational motion designer and technical instructor. "
                                "Return one compact, valid scene storyboard that teaches the narration."
                            ),
                            max_retries=0,
                            prefer_native=False,
                        )
                        item = next((x for x in single.scenes if x.scene_id == scene.id), None)
                        if item is None:
                            raise ValueError(f"Missing rescued storyboard for scene {scene.id}")
                        planned.append(self._finalize_storyboard(item, scene, topic))
                        llm_rescued_scene_ids.append(int(scene.id))
                        print(f"[STUDY STORYBOARD RESCUE] scene={scene.id} source=locked-llm")
                    except Exception as scene_exc:
                        fallback = self._finalize_storyboard(self._fallback(topic, scene), scene, topic)
                        planned.append(fallback)
                        deterministic_scene_ids.append(int(scene.id))
                        scene_reason = str(scene_exc).splitlines()[0][:140]
                        print(
                            f"[STUDY STORYBOARD RESCUE] scene={scene.id} "
                            f"source=deterministic reason={type(scene_exc).__name__}: {scene_reason}"
                        )

            storyboards.extend(planned)
            recent_summaries.extend(self._summary(sb) for sb in planned)
            offset += len(batch_scenes)

        # Cross-scene diversity repair can change layouts, so enforce semantic
        # invariants again afterwards and repair only the scenes that violate
        # the teaching contract instead of failing the whole workflow.
        storyboards = self._repair_cross_scene_repetition(storyboards)
        storyboards, quality_repairs = self._auto_repair_semantic_quality(
            storyboards, scenes, topic
        )
        deterministic_scene_ids.extend(quality_repairs)

        report = diversity_report(storyboards)
        quality = storyboard_quality_report(storyboards)
        deterministic_ratio = len(set(deterministic_scene_ids)) / max(1, len(storyboards))
        max_deterministic_ratio = float(os.getenv("STUDY_MAX_DETERMINISTIC_SCENE_RATIO", "0.25"))
        if deterministic_ratio > max_deterministic_ratio:
            raise RuntimeError(
                "Study storyboard fallback ratio is too high for production: "
                f"{deterministic_ratio:.0%} deterministic scenes; maximum "
                f"{max_deterministic_ratio:.0%}. Retry the stronger LLM instead of "
                "publishing generic fallback visuals."
            )
        if not self._quality_passes(quality):
            raise RuntimeError(
                "Study storyboard semantic quality gate failed after auto-repair: "
                f"score={quality['score']} specialized={quality['specialized_scene_pass_ratio']} "
                f"generic={quality['generic_object_ratio']} issues={quality['issues'][:4]}"
            )

        output_dir = artifact_subdir(state, "storyboards", self._output_root)
        output_path = output_dir / "study_storyboards.json"
        payload = {
            "version": "study-storyboard-v7.1-theory-first",
            "topic": topic,
            "scenes": [sb.model_dump() for sb in storyboards],
            "diversity": report,
            "semantic_quality": quality,
            "llm_rescued_scene_ids": sorted(set(llm_rescued_scene_ids)),
            "deterministic_scene_ids": sorted(set(deterministic_scene_ids)),
        }
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        state.metadata["study_storyboard_file"] = str(output_path)
        state.metadata["study_storyboard_diversity"] = report
        state.metadata["study_storyboard_semantic_quality"] = quality
        state.metadata["study_storyboard_llm_rescued_scene_ids"] = sorted(set(llm_rescued_scene_ids))
        state.metadata["study_storyboard_deterministic_scene_ids"] = sorted(set(deterministic_scene_ids))

        print(
            "[STUDY STORYBOARD] "
            f"scenes={len(storyboards)} unique_ratio={report['unique_ratio']} "
            f"max_adjacent_repeat={report['max_adjacent_repeat']}"
        )
        print(
            "[STUDY QUALITY] "
            f"score={quality['score']} "
            f"generic_ratio={quality['generic_object_ratio']} "
            f"specialized_pass={quality['specialized_scene_pass_ratio']} "
            f"dynamic={quality.get('dynamic_scene_ratio', 1.0)} "
            f"auto_repaired={len(set(quality_repairs))}"
        )
        if llm_rescued_scene_ids or deterministic_scene_ids:
            print(
                "[STUDY RESILIENCE] "
                f"llm_rescued={sorted(set(llm_rescued_scene_ids))} "
                f"deterministic={sorted(set(deterministic_scene_ids))}"
            )
        for sb in storyboards:
            kinds = "/".join(obj.kind for obj in sb.objects[:4])
            print(
                f"[STUDY STORYBOARD] scene={sb.scene_id} layout={sb.layout} "
                f"objects={kinds} beats={len(sb.beats)}"
            )
        return state

    def _finalize_storyboard(
        self, item: StudySceneStoryboard, scene: object, topic: str
    ) -> StudySceneStoryboard:
        narration = str(getattr(scene, "description", ""))
        cleaned = clean_storyboard(item, title=str(getattr(scene, "title", "")), topic=topic)
        cleaned = self._repair_topic_specific_teaching(cleaned, scene, topic)
        cleaned = self._repair_beginner_pedagogy(cleaned, scene, topic)
        cleaned = self._repair_semantic_requirements(cleaned, narration, topic)
        cleaned = self._repair_temporal_alignment(cleaned, scene, topic)
        cleaned = self._repair_analogy_grounding(cleaned, narration)
        cleaned = self._repair_cues(cleaned, narration)
        cleaned = self._repair_viewer_interaction(cleaned, narration=narration, topic=topic)
        cleaned = self._apply_motion_preferences(cleaned)
        return cleaned



    @staticmethod
    def _theory_points_from_narration(narration: str) -> list[str]:
        """Extract 3 concise theory points that stay grounded in the spoken text.

        The previous BEGINNER-FIRST implementation still converted EXPLAIN
        windows into semantic diagrams. That meant logs said phase=explain while
        the viewer immediately saw agents/tools/arrows. This helper keeps the
        first teaching beat textual and voice-grounded before any flow diagram.
        """
        text = re.sub(r"\s+", " ", str(narration or "")).strip()
        if not text:
            return []

        sentences = [
            x.strip(" -•\t")
            for x in re.split(r"(?<=[.!?])\s+", text)
            if x.strip()
        ]

        # If the narration uses one or two long spoken sentences, split only on
        # strong clause boundaries. We never invent a new fact here.
        expanded: list[str] = []
        for sentence in sentences:
            if len(sentence.split()) > 18:
                parts = [
                    p.strip(" ,;:-")
                    for p in re.split(r"[;:]\s+|,\s+(?=(?:and|but|while|which|so|because)\b)", sentence)
                    if p.strip()
                ]
                if len(parts) > 1:
                    expanded.extend(parts)
                else:
                    expanded.append(sentence)
            else:
                expanded.append(sentence)

        points: list[str] = []
        for item in expanded:
            item = re.sub(r"^(?:first|second|third|finally|in simple terms|simply put)[,:]?\s+", "", item, flags=re.I)
            item = item.strip()
            if not item:
                continue
            # Theory cards can wrap naturally; cap pathological rescue text but
            # avoid visible ellipsis/truncation in normal beginner narration.
            words = item.split()
            if len(words) > 24:
                item = " ".join(words[:24]).rstrip(" ,;:-") + "."
            if item[-1:] not in ".!?":
                item += "."
            norm = re.sub(r"[^a-z0-9]+", " ", item.lower()).strip()
            if not norm or any(re.sub(r"[^a-z0-9]+", " ", x.lower()).strip() == norm for x in points):
                continue
            points.append(item)
            if len(points) == 3:
                break

        # A 34-48 word study scene normally gives 2-4 spoken sentences. When
        # only two survive, split the longest point at a natural conjunction.
        if len(points) < 3 and points:
            source = max(points, key=lambda x: len(x.split()))
            clauses = [
                c.strip(" ,;:-")
                for c in re.split(r"\s+(?:and|but|so|while)\s+", source)
                if len(c.strip().split()) >= 4
            ]
            if len(clauses) >= 2:
                rebuilt = [p for p in points if p != source]
                for clause in clauses:
                    if clause[-1:] not in ".!?":
                        clause += "."
                    rebuilt.append(clause)
                points = rebuilt[:3]

        return points[:3]

    @classmethod
    def _repair_beginner_pedagogy(
        cls,
        sb: StudySceneStoryboard,
        scene: object,
        topic: str,
    ) -> StudySceneStoryboard:
        """Enforce the universal beginner sequence: explain first, flow second.

        The renderer previously tried to infer the teaching job from keywords.
        That made voice and figures drift apart and caused unrelated chapters to
        reuse the same agent/tool/security composition. ContentProductionAgent
        now assigns an explicit learning phase; this method turns that phase
        into a visual contract while preserving topic-specific objects.
        """
        phase = str(getattr(scene, "learning_phase", "auto") or "auto").lower()
        chapter = str(getattr(scene, "chapter_title", "") or getattr(scene, "title", "") or topic)
        narration = str(getattr(scene, "description", "") or "")
        if phase == "auto":
            lower = f"{chapter} {narration}".lower()
            if int(getattr(scene, "id", 0) or 0) == 1:
                phase = "hook"
            elif any(term in lower for term in ("implementation", "python", "javascript", "code", "function")):
                phase = "implementation"
            elif any(term in lower for term in ("verify", "verification", "testing", "test ", "validate", "edge case")):
                phase = "verify"
            elif any(term in lower for term in ("recap", "conclusion", "what it means", "takeaway")):
                phase = "recap"
            else:
                phase = "explain"
        if phase not in {
            "hook", "explain", "flow", "example", "implementation", "verify", "recap", "cta"
        }:
            phase = "explain"
        base = sb.model_copy(update={"learning_phase": phase, "chapter_title": chapter[:90]})

        if phase in {"hook", "cta"}:
            return base

        def grounded(objects: list[StudyVisualObject], limit: int) -> list[StudyVisualObject]:
            # Current narration/chapter beats topic-level grounding. Otherwise a
            # broad topic token such as "AI Agent" survives every scene and the
            # same icon appears even while the voice is explaining memory, MCP,
            # evaluation, or failure handling.
            preferred = [
                obj for obj in objects
                if cls._label_grounded_in_narration(obj.label, narration)
                or cls._label_grounded_in_narration(obj.label, chapter)
            ]
            topic_only = [
                obj for obj in objects
                if obj not in preferred and cls._label_grounded_in_narration(obj.label, topic)
            ][:1]
            ordered: list[StudyVisualObject] = []
            seen: set[str] = set()
            for obj in [*preferred, *topic_only, *objects]:
                key = obj.id
                if key in seen:
                    continue
                seen.add(key)
                ordered.append(obj)
                if len(ordered) >= limit:
                    break

            # Relabel ungrounded support objects from concrete noun phrases in
            # this exact narration window. Keep the semantic kind so rendering
            # stays meaningful, but make the visible words match what is heard.
            phrases = [
                phrase for phrase in cls._noun_phrases(narration)
                if cls._good_label(phrase, topic, chapter)
            ]
            used = {obj.label.lower() for obj in ordered}
            repaired: list[StudyVisualObject] = []
            for obj in ordered:
                if (
                    cls._label_grounded_in_narration(obj.label, narration)
                    or cls._label_grounded_in_narration(obj.label, chapter)
                    or (not repaired and cls._label_grounded_in_narration(obj.label, topic))
                ):
                    repaired.append(obj)
                    continue
                replacement = next((p for p in phrases if p.lower() not in used), None)
                if replacement:
                    used.add(replacement.lower())
                    repaired.append(obj.model_copy(update={"label": replacement[:48]}))
                else:
                    repaired.append(obj)
            return repaired

        if phase == "explain":
            # THEORY FIRST. Do not use agent/tool/process figures here. The
            # learner first gets 3 voice-grounded points; the next FLOW scene
            # converts the same chapter into a cause -> action -> result diagram.
            points = cls._theory_points_from_narration(narration)
            if len(points) < 3:
                # Keep the fallback grounded in this exact narration/chapter.
                phrases = [
                    p for p in cls._noun_phrases(narration)
                    if cls._good_label(p, topic, chapter)
                ]
                for phrase in phrases:
                    sentence = phrase.strip().rstrip(".") + "."
                    if sentence.lower() not in {p.lower() for p in points}:
                        points.append(sentence)
                    if len(points) == 3:
                        break
            while len(points) < 3:
                grounded_objects = grounded(list(base.objects), 3)
                fallback = grounded_objects[min(len(points), len(grounded_objects) - 1)].label if grounded_objects else chapter
                points.append(str(fallback).strip().rstrip(".") + ".")

            headings = ("Definition", "Key idea", "Why it matters")
            slots = ("wide_top", "wide_mid", "wide_bottom")
            objects = [
                StudyVisualObject(
                    id=f"theory_{idx+1}",
                    kind="theory_point",
                    label=headings[idx],
                    detail=[points[idx]],
                    slot=slots[idx],
                )
                for idx in range(3)
            ]
            beats: list[StudyVisualBeat] = []
            for idx, (obj, point) in enumerate(zip(objects, points)):
                cue_words = " ".join(point.split()[:5]).strip(" .,:;—-") or f"point {idx+1}"
                beats.append(StudyVisualBeat(cue=cue_words, action="reveal", target=obj.id, weight=2))
            beats.append(StudyVisualBeat(cue="remember", action="select", target=objects[1].id, weight=2))
            return base.model_copy(update={
                "purpose": f"Teach the plain-language theory of {chapter} before showing the mechanism.",
                "layout": "stack",
                "objects": objects,
                "beats": beats,
                "teaching_pattern": "concept_explain",
                "camera_style": "static",
                "motion_density": "low",
            })

        if phase == "flow":
            objects = grounded(list(base.objects), 5)
            # A useful flow needs at least three concrete stages. If the LLM
            # supplied fewer, derive compact nouns from the current narration
            # rather than inventing generic Input/Process/Result cards.
            existing_labels = {obj.label.lower() for obj in objects}
            noun_phrases = [
                phrase for phrase in cls._noun_phrases(narration)
                if phrase.lower() not in existing_labels and cls._good_label(phrase, topic, chapter)
            ]
            slots = ["left_mid", "center_top", "center_bottom", "right_mid", "right_bottom"]
            while len(objects) < 3 and noun_phrases:
                label = noun_phrases.pop(0)
                oid = f"phase_{len(objects)+1}"
                objects.append(StudyVisualObject(id=oid, kind="resource", label=label, slot=slots[len(objects)]))
            if len(objects) < 3:
                objects = list(base.objects[:3])

            # Re-slot deterministically; the renderer will normalize these into
            # a readable left-to-right diagram.
            flow_objects: list[StudyVisualObject] = []
            flow_slots = ["left_mid", "center_top", "center_bottom", "right_mid", "right_bottom"]
            for index, obj in enumerate(objects[:5]):
                flow_objects.append(obj.model_copy(update={"slot": flow_slots[index]}))

            beats: list[StudyVisualBeat] = [
                StudyVisualBeat(cue="flow starts", action="reveal", target=flow_objects[0].id)
            ]
            for prev, cur in zip(flow_objects, flow_objects[1:]):
                beats.append(StudyVisualBeat(cue="next step", action="reveal", target=cur.id))
                beats.append(StudyVisualBeat(
                    cue="moves to", action="send", target=prev.id,
                    source=prev.id, destination=cur.id, weight=2,
                ))
            beats.append(StudyVisualBeat(cue="flow result", action="select", target=flow_objects[-1].id, weight=2))
            return base.model_copy(update={
                "purpose": f"Show how {chapter} works as a visible cause-to-result flow.",
                "layout": "left_to_right",
                "objects": flow_objects,
                "beats": beats[:12],
                "teaching_pattern": "mechanism_flow",
                "camera_style": "follow",
                "motion_density": "high",
            })

        if phase == "example":
            return base.model_copy(update={
                "teaching_pattern": "worked_example",
                "camera_style": "guided",
                "motion_density": "medium",
            })

        if phase == "implementation":
            return base.model_copy(update={
                "teaching_pattern": "worked_example",
                "camera_style": "focus" if base.layout == "code_plus_state" else "guided",
            })

        if phase == "verify":
            # Verification is not automatically a security boundary. Only keep
            # ALLOW/BLOCK grammar when the narration explicitly discusses a
            # permission/security boundary. Otherwise use comparison/testing.
            lower = narration.lower()
            security = any(term in lower for term in (
                "permission", "authorized", "unauthorized", "security", "private file",
                "access control", "blocked", "reject", "sandbox", "path traversal",
            ))
            updates: dict[str, object] = {
                "teaching_pattern": "verification",
                "camera_style": "guided",
            }
            if base.layout == "boundary" and not security:
                updates["layout"] = "split"
            return base.model_copy(update=updates)

        if phase == "recap":
            return base.model_copy(update={
                "teaching_pattern": "recap",
                "camera_style": "guided",
                "motion_density": "low",
            })

        return base

    @staticmethod
    def _apply_motion_preferences(sb: StudySceneStoryboard) -> StudySceneStoryboard:
        """Apply optional user-level motion overrides without changing semantics."""
        updates: dict[str, object] = {}
        camera = os.getenv("STUDY_CAMERA_STYLE", "auto").strip().lower()
        if camera in {"static", "guided", "follow", "focus", "cinematic"}:
            updates["camera_style"] = camera
        density = os.getenv("STUDY_MOTION_DENSITY", "auto").strip().lower()
        if density in {"low", "medium", "high"}:
            updates["motion_density"] = density
        environment = os.getenv("STUDY_ENVIRONMENT", "auto").strip().lower()
        if environment in {
            "technical", "data_space", "code_lab", "browser_space", "document_space",
            "analogy_warm", "security_boundary", "science_lab", "clean_light",
        }:
            updates["environment"] = environment
        return sb.model_copy(update=updates) if updates else sb

    @staticmethod
    def _quality_passes(quality: dict[str, object]) -> bool:
        return (
            float(quality["score"]) >= 82.0
            and float(quality["specialized_scene_pass_ratio"]) >= 0.95
            and float(quality["generic_object_ratio"]) <= 0.40
            and float(quality.get("dynamic_scene_ratio", 1.0)) >= 0.85
            and float(quality.get("placeholder_label_ratio", 0.0)) <= 0.08
            and float(quality.get("overloaded_scene_ratio", 0.0)) <= 0.30
            # Phase-aware ratio: mandatory EXPLAIN/ FLOW layouts are excluded
            # from this diversity gate. Flexible phases still must not collapse
            # into one template.
            and float(quality.get("layout_dominance_ratio", 0.0)) <= 0.55
            and float(quality.get("high_similarity_pair_ratio", 0.0)) <= 0.25
        )

    @classmethod
    def _auto_repair_semantic_quality(
        cls,
        storyboards: list[StudySceneStoryboard],
        scenes: list[object],
        topic: str,
    ) -> tuple[list[StudySceneStoryboard], list[int]]:
        scene_by_id = {int(getattr(scene, "id")): scene for scene in scenes}
        repaired: list[StudySceneStoryboard] = []
        changed: list[int] = []

        for sb in storyboards:
            scene = scene_by_id.get(sb.scene_id)
            if scene is None:
                repaired.append(sb)
                continue
            narration = str(getattr(scene, "description", ""))
            fixed = cls._repair_topic_specific_teaching(sb, scene, topic)
            fixed = cls._repair_beginner_pedagogy(fixed, scene, topic)
            fixed = cls._repair_semantic_requirements(fixed, narration, topic)
            fixed = cls._repair_temporal_alignment(fixed, scene, topic)
            fixed = cls._repair_analogy_grounding(fixed, narration)
            fixed = cls._repair_cues(fixed, narration)
            fixed = cls._repair_viewer_interaction(fixed, narration=narration, topic=topic)
            if fixed.model_dump() != sb.model_dump():
                changed.append(sb.scene_id)
            repaired.append(fixed)

        quality = storyboard_quality_report(repaired)
        if cls._quality_passes(quality):
            return repaired, changed

        issue_ids: set[int] = set()
        for issue in quality.get("issues", []):
            match = re.search(r"scene\s+(\d+)", str(issue))
            if match:
                issue_ids.add(int(match.group(1)))

        # Recover only invalid scenes. This preserves good LLM-directed scenes
        # while guaranteeing strict semantic contracts for specialized layouts.
        if issue_ids:
            second_pass: list[StudySceneStoryboard] = []
            for sb in repaired:
                if sb.scene_id not in issue_ids:
                    second_pass.append(sb)
                    continue
                scene = scene_by_id.get(sb.scene_id)
                if scene is None:
                    second_pass.append(sb)
                    continue
                fallback = cls._fallback(topic, scene)
                fallback = clean_storyboard(
                    fallback,
                    title=str(getattr(scene, "title", "")),
                    topic=topic,
                )
                fallback = cls._repair_topic_specific_teaching(fallback, scene, topic)
                fallback = cls._repair_beginner_pedagogy(fallback, scene, topic)
                fallback = cls._repair_semantic_requirements(
                    fallback, str(getattr(scene, "description", "")), topic
                )
                fallback = cls._repair_temporal_alignment(fallback, scene, topic)
                fallback = cls._repair_analogy_grounding(
                    fallback, str(getattr(scene, "description", ""))
                )
                fallback = cls._repair_cues(
                    fallback, str(getattr(scene, "description", ""))
                )
                fallback = cls._repair_viewer_interaction(
                    fallback, narration=str(getattr(scene, "description", "")), topic=topic
                )
                second_pass.append(fallback)
                changed.append(sb.scene_id)
                print(
                    f"[STUDY QUALITY REPAIR] scene={sb.scene_id} "
                    "replaced with semantic-safe deterministic storyboard"
                )
            repaired = cls._repair_cross_scene_repetition(second_pass)

        return repaired, sorted(set(changed))

    @staticmethod
    def _prompt(topic: str, scenes: list[object], recent: list[str]) -> str:
        scene_payload = []
        viewer_market = os.getenv("STUDY_VIEWER_MARKET", "US").strip().upper() or "US"
        for scene in scenes:
            scene_payload.append(
                {
                    "scene_id": int(getattr(scene, "id")),
                    "title": str(getattr(scene, "title", "")),
                    "narration": str(getattr(scene, "description", "")),
                    "visual_type": str(getattr(scene, "visual_type", "")),
                    "key_elements": [str(v) for v in getattr(scene, "key_elements", [])],
                    "learning_phase": str(getattr(scene, "learning_phase", "explain")),
                    "chapter_title": str(getattr(scene, "chapter_title", getattr(scene, "title", ""))),
                    "chapter_scene_index": int(getattr(scene, "chapter_scene_index", 1)),
                    "chapter_scene_count": int(getattr(scene, "chapter_scene_count", 1)),
                    "scene_role": "hook" if int(getattr(scene, "id")) == 1 else "current_narration",
                }
            )
        return f"""
Create a concrete animation storyboard for every scene below.

TOPIC: {topic}
PRIMARY VIEWER MARKET: {viewer_market}
RECENT STORYBOARD SIGNATURES TO AVOID COPYING: {json.dumps(recent)}
SCENES:
{json.dumps(scene_payload, ensure_ascii=False, indent=2)}

NON-NEGOTIABLE STUDY-VIDEO RULES:
- Motion must teach the narration. Do not animate merely for movement.
- BEGINNER-FIRST PEDAGOGY: `learning_phase` is a hard contract. For EXPLAIN scenes, render three concise THEORY POINTS grounded in the exact narration (Definition, Key idea, Why it matters); do NOT use process figures or dump the full mechanism yet. For FLOW scenes, reuse only the needed concepts and show the mechanism as a clear left-to-right cause -> action -> result diagram. This EXPLAIN -> FLOW sequence must be obvious to a beginner.
- TEMPORAL LOCK: render only concepts explicitly present in the CURRENT scene narration. Never preview security, code, formulas, tools, or later-section concepts before the narration says them.
- Scene 1 is the HOOK: visualize the exact learner problem first, then a concrete mechanism/payoff from the hook. In the first 30 seconds prefer problem -> visible failure/cost -> mechanism -> payoff. It must not jump ahead to detailed implementation/security unless those words are in the hook.
- VISUAL VERB FIRST: decide what the learner should literally SEE happen (split, rank, route, compare, reject, transform, execute, verify), then choose objects. A diagram with arrows but no changing state is not enough.
- ONE TEACHING IDEA PER SCENE: identify the single sentence the viewer should understand after this scene. Every visible object must help explain that idea. Remove decorative or orphan objects that do not participate in a beat.
- RELATIONSHIP FIRST: the viewer must be able to answer “what is this object, why is it here, and what changed because of it?” Prefer visible cause -> action -> result. When data moves, name the payload (question, evidence, vector, context, answer), never generic “data”.
- CONTINUITY WITHOUT CLUTTER: when a chapter continues a process, carry forward only the one object needed to connect the previous result to the next step, then visually transform/reuse it. Do not restart every scene from the same User Query/Model anchor.
- RELATABLE BEFORE ABSTRACT: for a new abstract concept, first use a familiar concrete behavior or UI when it genuinely clarifies the idea (search field, book, document, highlighted match, context window), then map to the technical representation. Do not force an analogy if it adds another abstraction.
- Do NOT reuse one generic flowchart, orbit, card grid, or zoom treatment across scenes. Two consecutive scenes may not use the same layout + object-kind family + action family unless the second scene visibly changes the state.
- For RAG/retrieval lessons, prefer distinct operations by concept: document chunking physically splits a document; embeddings transform chunks into vectors; similarity search ranks/selects candidates; augmentation visibly adds retrieved context to the prompt; generation produces an answer linked back to sources; verification contrasts supported vs unsupported output; recap compresses to Query -> Retrieve -> Augment -> Generate -> Verify.
- A repeated section must EVOLVE state: setup -> mechanism -> result -> verification, not redraw the same diagram.
- Labels must be concrete nouns/terms from the current narration (Host, Client, Server, JSON-RPC, file path, schema, etc.).
- Never use filler labels such as Context, Core idea, This, Finally, Today, Learn, Mechanism, or the full scene title.
- Use 3-7 visual objects for normal scenes and 5-10 beats per scene. Use 8-9 objects only when a genuinely complex worked example needs them. Long narration needs enough beats to remain visually active.
- CLARITY HIERARCHY: keep one focal concept at a time; progressively reveal supporting objects instead of showing everything at once. Prefer one primary relationship over a dense dashboard.
- Prefer meaningful object kinds. Software/AI: person/place/device/app/sensor/file/folder/book/database/browser/search_ui/code/function/api/array/packet/connector/shield/lock/gate/agent/model/host/client/server/tool/resource/prompt/context_window/answer_panel/point_cloud. Math/data: equation/graph/chart/number_line/shape/quantity/vector/table/array/point_cloud. Science: atom/molecule/wave/experiment/graph/chart/quantity/vector.
- Use node/text/badge only when a more specific object kind genuinely does not fit.
- `cue` MUST be 2-8 consecutive words copied verbatim from that scene narration. Cues are used to synchronize animation to speech; never write abstract cues such as "show the mechanism".
- Spread cues from early to middle to late narration. Do not place all beats in the opening sentence.
- For code scenes: create one `code` object whose `detail` contains 3-6 short executable/pseudocode lines supported by narration, plus state/output objects. Do not invent product APIs.
- For algorithm scenes: use `array` detail values and pointer/selection beats.
- For math scenes: show the actual relationship with equation/graph/number_line/shape/quantity objects; animate substitution, comparison, selection, or transformation instead of drawing software boxes.
- For physics/science scenes: use vector/wave/graph/quantity/experiment/atom/molecule objects as appropriate and animate the changing state or measured relationship.
- Every scene should include at least one meaningful state-changing beat (move/send/return/transform/replace/split/merge/scan/stream/step_code/allow/reject/select/compare) unless the narration is purely a short definition.
- Use `split` when one visual is physically divided into pieces, `scan` when candidates are inspected/ranked, `merge` when evidence/query parts are assembled into one context, and `stream` when an answer/result is progressively produced. Do not substitute decorative arrows for these operations.
- Choose `environment` and `camera_style` intentionally. Use code_lab for code, document_space for document/chunking, data_space for retrieval/vector scenes, browser_space for browser demonstrations, analogy_warm for real-world analogies, security_boundary for allow/reject scenes, and technical otherwise. Prefer guided/follow/focus camera styles over random zooms; use static only when motion would hurt comprehension.
- For architecture/protocol scenes: use concrete component object kinds and send/return/connect beats.
- For analogies: use real-world object kinds such as person/place/file/folder first, then include the concrete technical objects and transform/map each analogy object into its technical counterpart. Example: Customer(person) -> Host(host), Waiter(person) -> Client(client), Kitchen(place) -> MCP Server(server). Never represent the analogy only as generic nodes.
- For security/validation: visually show valid and invalid paths, allow/reject, and the protected boundary.
- Reference keywords should describe scene-specific imagery, never generic "technology".
- Every beat must reference existing object IDs. Use finite allowed actions only.
- U.S. VIEWER CLARITY: use short American-English labels, direct wording, and familiar left-to-right cause/effect flow unless the subject itself requires another layout.
- VIEWER FLOW: normal YouTube study mode is uninterrupted explanation. Do NOT add quiz cards, pause-and-predict overlays, multiple-choice questions, or recall prompts unless the narration itself explicitly asks the viewer a question. Questions must never cover the main teaching visual.
- ENDING: a recap/takeaway scene must consolidate the topic-specific mental model and must not introduce a generic execution loop or a new unrelated abstraction.
- Never use engagement bait, fake urgency, or decorative questions. The interaction must reinforce the learning objective.
- Stay factual: do not introduce claims not present in narration.

Return one storyboard per supplied scene_id, in the same order.
""".strip()

    @classmethod
    def _repair_viewer_interaction(
        cls,
        sb: StudySceneStoryboard,
        *,
        narration: str = "",
        topic: str = "",
    ) -> StudySceneStoryboard:
        """Add sparse, specific retrieval/prediction prompts for active viewing.

        The prompt must be answerable from what is already visible. Generic
        "where does it go next?" questions are used only as a last resort.
        """
        enabled = os.getenv("STUDY_ACTIVE_CHECKS", "off").strip().lower() in {"1", "true", "yes", "on"}
        if not enabled:
            return sb.model_copy(update={
                "interaction_prompt": None,
                "interaction_answer": None,
                "interaction_choices": [],
                "interaction_style": None,
            })

        try:
            every = int(os.getenv("STUDY_ACTIVE_CHECK_EVERY", "4"))
        except ValueError:
            every = 4
        every = max(3, min(8, every))
        if sb.scene_id == 1 or sb.scene_id % every != 0 or sb.teaching_pattern == "recap":
            return sb.model_copy(update={
                "interaction_prompt": None,
                "interaction_answer": None,
                "interaction_choices": [],
                "interaction_style": None,
            })

        scene_lower = str(narration or "").lower()
        domain_lower = f"{topic} {narration}".lower()
        labels = [o.label for o in sb.objects]
        by_id = {obj.id: obj for obj in sb.objects}
        candidates = [
            beat for beat in sb.beats
            if beat.action in {
                "send", "return", "connect", "allow", "reject", "compare",
                "select", "step_code", "transform", "replace",
            }
        ]
        if not candidates:
            return sb

        # Topic-aware checks are deliberately concrete and short. Distractors
        # are conceptual categories, never invented product facts.
        if cls._is_rag_text(domain_lower):
            if sb.teaching_pattern == "retrieval_match":
                answer = next((x for x in labels if "nearest" in x.lower()), None) or next((x for x in labels if "match" in x.lower()), "Nearest Chunk")
                return sb.model_copy(update={
                    "interaction_prompt": "Which result should retrieval choose?",
                    "interaction_answer": answer,
                    "interaction_choices": [answer, "Random Chunk", "Largest File"],
                    "interaction_style": "quick_check",
                })
            if sb.teaching_pattern == "context_build":
                return sb.model_copy(update={
                    "interaction_prompt": "What gets added before generation?",
                    "interaction_answer": "Retrieved Context",
                    "interaction_choices": ["Retrieved Context", "New Training", "Random Text"],
                    "interaction_style": "recall",
                })
            if sb.teaching_pattern == "verification":
                if any(x in scene_lower for x in ("test", "testing", "evaluate", "evaluation")):
                    return sb.model_copy(update={
                        "interaction_prompt": "What should the test compare?",
                        "interaction_answer": "Answer vs Evidence",
                        "interaction_choices": ["Answer vs Evidence", "Answer Length", "Model Name"],
                        "interaction_style": "quick_check",
                    })
                return sb.model_copy(update={
                    "interaction_prompt": "Which answer should pass verification?",
                    "interaction_answer": "Source-backed Answer",
                    "interaction_choices": ["Source-backed Answer", "Unsupported Answer"],
                    "interaction_style": "quick_check",
                })
            if sb.teaching_pattern == "worked_example" and "chunk" in scene_lower:
                return sb.model_copy(update={
                    "interaction_prompt": "What happens before retrieval?",
                    "interaction_answer": "Split into Chunks",
                    "interaction_choices": ["Split into Chunks", "Retrain Model", "Delete Sources"],
                    "interaction_style": "recall",
                })
            if "embedding" in scene_lower:
                return sb.model_copy(update={
                    "interaction_prompt": "What does a text chunk become?",
                    "interaction_answer": "Embedding Vector",
                    "interaction_choices": ["Embedding Vector", "Final Answer", "API Key"],
                    "interaction_style": "recall",
                })
            if any(x in scene_lower for x in ("generate", "generation")):
                return sb.model_copy(update={
                    "interaction_prompt": "What should the answer stay linked to?",
                    "interaction_answer": "Retrieved Source",
                    "interaction_choices": ["Retrieved Source", "Random Text", "Model Name"],
                    "interaction_style": "recall",
                })
            if sb.teaching_pattern == "compare_paths":
                return sb.model_copy(update={
                    "interaction_prompt": "What most affects answer quality here?",
                    "interaction_answer": "Retrieval Quality",
                    "interaction_choices": ["Retrieval Quality", "Font Size", "Video Length"],
                    "interaction_style": "quick_check",
                })
            if "mental model" in scene_lower or "external documents" in scene_lower:
                return sb.model_copy(update={
                    "interaction_prompt": "What supplies fresh context to RAG?",
                    "interaction_answer": "External Documents",
                    "interaction_choices": ["External Documents", "Model Memory", "Random Text"],
                    "interaction_style": "recall",
                })

        beat = candidates[-1]
        target = by_id.get(beat.destination or beat.target) or by_id.get(beat.target)
        source = by_id.get(beat.source or "")
        answer = (target.label if target else (beat.label or "Highlighted Result")).strip()
        answer = cls._compact_phrase(answer, max_words=5, max_chars=56)

        if beat.action in {"send", "return", "connect"} and source and target:
            prompt, style = f"Where does {source.label} send it?", "predict"
            alternatives = [x for x in labels if x not in {source.label, answer}][:2]
            choices = [answer, *alternatives][:3]
        elif beat.action in {"allow", "reject"}:
            prompt, style = "Should this path pass the boundary?", "quick_check"
            choices = ["Allow", "Block"]
            answer = "Allow" if beat.action == "allow" else "Block"
        elif beat.action == "step_code":
            prompt, style = "What changes after this code step?", "predict"
            choices = [answer]
        elif beat.action in {"transform", "replace"} and source and target:
            prompt, style = f"What does {source.label} become?", "recall"
            choices = [answer]
        else:
            prompt, style = "Which visible result best fits?", "quick_check"
            choices = [answer]

        return sb.model_copy(update={
            "interaction_prompt": cls._compact_phrase(prompt, max_words=9, max_chars=88),
            "interaction_answer": answer,
            "interaction_choices": [cls._compact_phrase(x, max_words=5, max_chars=46) for x in choices if x][:3],
            "interaction_style": style,
        })


    @staticmethod
    def _compact_phrase(value: str, *, max_words: int = 6, max_chars: int = 64) -> str:
        words = re.sub(r"\s+", " ", str(value or "")).strip().split()
        out: list[str] = []
        for word in words[:max_words]:
            candidate = " ".join([*out, word])
            if out and len(candidate) > max_chars:
                break
            out.append(word)
        return " ".join(out) or "Result"

    @staticmethod
    def _is_rag_text(text: str) -> bool:
        lower = str(text or "").lower()
        return any(term in lower for term in (
            "retrieval augmented", "retrieval-augmented", "rag ", " rag", "retriever",
            "vector database", "vector store", "embedding", "chunking", "retrieval",
        ))

    @staticmethod
    def _scene_part_index(title: str) -> int:
        match = re.search(r"[—-]\s*(\d+)\s*$", str(title or "").strip())
        return int(match.group(1)) if match else 1

    @classmethod
    def _rag_chapter_storyboard(
        cls,
        sb: StudySceneStoryboard,
        *,
        title: str,
        narration: str,
        scene_id: int,
    ) -> StudySceneStoryboard | None:
        """Direct recurring RAG chapters as a coherent visual lesson.

        The previous engine matched broad words such as `query` and `retrieval`,
        which repeatedly collapsed different ideas into the same User Query →
        Retriever diagram.  This chapter director chooses one *teaching event*
        per scene and gives each phase a different visual grammar.
        """
        title_lower = title.lower().strip()
        base_title = re.sub(r"\s+[—-]\s*\d+\s*$", "", title_lower).strip()
        part = cls._scene_part_index(title)

        def finish(*, purpose: str, layout: str, objects: list[StudyVisualObject],
                   beats: list[StudyVisualBeat], pattern: str = "progressive_flow",
                   env: str = "auto", camera: str = "guided", motion: str = "medium"):
            return sb.model_copy(update={
                "purpose": purpose,
                "layout": layout,
                "objects": objects,
                "beats": beats,
                "teaching_pattern": pattern,
                "reference_keywords": [obj.label for obj in objects[:5]],
                "environment": env,
                "camera_style": camera,
                "motion_density": motion,
                "interaction_prompt": None,
                "interaction_answer": None,
                "interaction_choices": [],
                "interaction_style": None,
            })

        if scene_id == 1:
            objects = [
                StudyVisualObject(id="question", kind="search_ui", label="Your Question", slot="left_mid"),
                StudyVisualObject(id="model", kind="model", label="Language Model", slot="center_top"),
                StudyVisualObject(id="sources", kind="document", label="Private Sources", slot="center_bottom"),
                StudyVisualObject(id="answer", kind="answer_panel", label="Grounded Answer", slot="right_mid", detail=["Source 1", "Source 2"]),
            ]
            beats = [
                StudyVisualBeat(cue="question", action="reveal", target="question"),
                StudyVisualBeat(cue="model", action="send", target="question", source="question", destination="model", label="question", weight=2),
                StudyVisualBeat(cue="sources", action="reveal", target="sources"),
                StudyVisualBeat(cue="retrieve", action="send", target="sources", source="sources", destination="model", label="evidence", weight=2),
                StudyVisualBeat(cue="answer", action="stream", target="answer", source="model", weight=3),
                StudyVisualBeat(cue="grounded", action="connect", target="answer", source="answer", destination="sources", weight=2),
            ]
            return finish(
                purpose="Show the viewer's question, the missing private knowledge, and the grounded-answer payoff in one concrete interaction.",
                layout="browser_demo", objects=objects, beats=beats, pattern="problem_solution",
                env="browser_space", camera="guided", motion="high",
            )

        if base_title == "context":
            if part == 1:
                objects = [
                    StudyVisualObject(id="model", kind="model", label="Model Memory", slot="left_mid"),
                    StudyVisualObject(id="uncertain", kind="answer_panel", label="Incomplete Answer", slot="left_bottom", detail=["No fresh source"]),
                    StudyVisualObject(id="fresh", kind="book", label="Fresh Information", slot="right_top"),
                    StudyVisualObject(id="private", kind="document", label="Private Documents", slot="right_bottom"),
                ]
                beats = [
                    StudyVisualBeat(cue="model", action="reveal", target="model"),
                    StudyVisualBeat(cue="answer", action="stream", target="uncertain", source="model", weight=2),
                    StudyVisualBeat(cue="information", action="reveal", target="fresh"),
                    StudyVisualBeat(cue="documents", action="reveal", target="private"),
                    StudyVisualBeat(cue="gap", action="compare", target="fresh", source="model", destination="fresh", weight=2),
                ]
                return finish(
                    purpose="Make the information gap visible: the model answers from memory while newer/private sources sit outside it.",
                    layout="split", objects=objects, beats=beats, pattern="compare_paths",
                    env="document_space", camera="focus",
                )
            objects = [
                StudyVisualObject(id="question", kind="search_ui", label="Question", slot="left_mid"),
                StudyVisualObject(id="sources", kind="document", label="External Sources", slot="center_bottom"),
                StudyVisualObject(id="retriever", kind="vector_store", label="Retriever", slot="center_top"),
                StudyVisualObject(id="context", kind="context_window", label="Retrieved Context", slot="right_top", detail=["Relevant passage", "Supporting passage"]),
                StudyVisualObject(id="answer", kind="answer_panel", label="Grounded Answer", slot="right_bottom", detail=["Source 1"]),
            ]
            beats = [
                StudyVisualBeat(cue="question", action="reveal", target="question"),
                StudyVisualBeat(cue="retrieve", action="send", target="question", source="question", destination="retriever", label="question", weight=2),
                StudyVisualBeat(cue="sources", action="reveal", target="sources"),
                StudyVisualBeat(cue="context", action="merge", target="context", source="sources", weight=3),
                StudyVisualBeat(cue="answer", action="stream", target="answer", source="context", weight=3),
            ]
            return finish(
                purpose="Bridge the information gap by retrieving outside evidence and turning it into grounded context.",
                layout="freeform", objects=objects, beats=beats, pattern="problem_solution",
                env="document_space", camera="follow", motion="high",
            )

        if "core definition" in base_title and "information gap" in base_title:
            if part == 1:
                objects = [
                    StudyVisualObject(id="question", kind="search_ui", label="Question", slot="left_mid"),
                    StudyVisualObject(id="store", kind="vector_store", label="Knowledge Store", slot="center"),
                    StudyVisualObject(id="matches", kind="document", label="Relevant Sources", slot="right_mid"),
                ]
                beats = [
                    StudyVisualBeat(cue="question", action="reveal", target="question"),
                    StudyVisualBeat(cue="retrieve", action="send", target="question", source="question", destination="store", label="question", weight=2),
                    StudyVisualBeat(cue="relevant", action="scan", target="store", source="question", weight=2),
                    StudyVisualBeat(cue="sources", action="return", target="matches", source="store", destination="matches", label="evidence", weight=2),
                ]
                return finish(purpose="Teach retrieval as an explicit search for relevant outside evidence.", layout="left_to_right", objects=objects, beats=beats, pattern="retrieval_match", env="data_space", camera="follow")
            if part == 2:
                objects = [
                    StudyVisualObject(id="chunk", kind="document", label="Text Chunk", slot="left_mid"),
                    StudyVisualObject(id="vector", kind="vector", label="Embedding", slot="center_top"),
                    StudyVisualObject(id="space", kind="point_cloud", label="Semantic Space", slot="center_bottom"),
                    StudyVisualObject(id="store", kind="vector_store", label="Vector Store", slot="right_mid"),
                ]
                beats = [
                    StudyVisualBeat(cue="chunk", action="reveal", target="chunk"),
                    StudyVisualBeat(cue="embedding", action="transform", target="vector", source="chunk", weight=2),
                    StudyVisualBeat(cue="meaning", action="transform", target="space", source="vector", weight=2),
                    StudyVisualBeat(cue="store", action="send", target="vector", source="vector", destination="store", label="vector", weight=2),
                ]
                return finish(purpose="Show text becoming a semantic vector instead of another box-and-arrow abstraction.", layout="left_to_right", objects=objects, beats=beats, env="data_space", camera="guided", motion="high")
            if part == 3:
                objects = [
                    StudyVisualObject(id="question", kind="search_ui", label="Question", slot="left_top"),
                    StudyVisualObject(id="evidence", kind="document", label="Retrieved Evidence", slot="left_bottom"),
                    StudyVisualObject(id="context", kind="context_window", label="Augmented Context", slot="right_mid", detail=["Question", "Evidence"]),
                ]
                beats = [
                    StudyVisualBeat(cue="question", action="reveal", target="question"),
                    StudyVisualBeat(cue="evidence", action="reveal", target="evidence"),
                    StudyVisualBeat(cue="context", action="merge", target="context", source="evidence", weight=3),
                    StudyVisualBeat(cue="prompt", action="connect", target="context", source="question", destination="context", weight=2),
                ]
                return finish(purpose="Make augmentation literal by assembling the question and retrieved evidence into one context window.", layout="split", objects=objects, beats=beats, pattern="context_build", env="document_space", camera="guided", motion="high")
            objects = [
                StudyVisualObject(id="context", kind="context_window", label="Augmented Context", slot="left_mid", detail=["Question", "Evidence"]),
                StudyVisualObject(id="model", kind="model", label="Language Model", slot="center"),
                StudyVisualObject(id="answer", kind="answer_panel", label="Grounded Answer", slot="right_top", detail=["Source 1", "Source 2"]),
                StudyVisualObject(id="source", kind="document", label="Source Evidence", slot="right_bottom"),
            ]
            beats = [
                StudyVisualBeat(cue="context", action="reveal", target="context"),
                StudyVisualBeat(cue="model", action="send", target="context", source="context", destination="model", label="context", weight=2),
                StudyVisualBeat(cue="answer", action="stream", target="answer", source="model", weight=3),
                StudyVisualBeat(cue="source", action="reveal", target="source"),
                StudyVisualBeat(cue="grounded", action="connect", target="answer", source="answer", destination="source", weight=2),
            ]
            return finish(purpose="Finish the definition by showing generation and the evidence relationship the viewer should remember.", layout="browser_demo", objects=objects, beats=beats, env="browser_space", camera="focus", motion="high")

        if "open-book exam mental model" in base_title:
            if part == 1:
                objects = [
                    StudyVisualObject(id="student", kind="person", label="Student", slot="left_mid"),
                    StudyVisualObject(id="question", kind="document", label="Exam Question", slot="center_top"),
                    StudyVisualObject(id="book", kind="book", label="Open Notes", slot="center_bottom"),
                    StudyVisualObject(id="answer", kind="resource", label="Supported Answer", slot="right_mid"),
                ]
                beats = [
                    StudyVisualBeat(cue="exam", action="reveal", target="question"),
                    StudyVisualBeat(cue="open-book", action="reveal", target="book"),
                    StudyVisualBeat(cue="look", action="send", target="book", source="question", destination="book", label="look up", weight=2),
                    StudyVisualBeat(cue="answer", action="transform", target="answer", source="book", weight=2),
                ]
                return finish(purpose="Use the open-book exam as a literal, relatable analogy before returning to technical terms.", layout="freeform", objects=objects, beats=beats, pattern="worked_example", env="analogy_warm", camera="guided")
            if part == 2:
                objects = [
                    StudyVisualObject(id="student", kind="person", label="Student", slot="left_top"),
                    StudyVisualObject(id="book", kind="book", label="Open Notes", slot="left_bottom"),
                    StudyVisualObject(id="model", kind="model", label="Language Model", slot="right_top"),
                    StudyVisualObject(id="context", kind="context_window", label="Retrieved Context", slot="right_bottom", detail=["Relevant passage"]),
                ]
                beats = [
                    StudyVisualBeat(cue="student", action="reveal", target="student"),
                    StudyVisualBeat(cue="notes", action="reveal", target="book"),
                    StudyVisualBeat(cue="model", action="transform", target="model", source="student", weight=2),
                    StudyVisualBeat(cue="context", action="transform", target="context", source="book", weight=3),
                ]
                return finish(purpose="Map the analogy to RAG: the student becomes the model and open notes become retrieved context.", layout="analogy_map", objects=objects, beats=beats, pattern="worked_example", env="analogy_warm", camera="focus")
            objects = [
                StudyVisualObject(id="question", kind="search_ui", label="Question", slot="left_mid"),
                StudyVisualObject(id="retriever", kind="vector_store", label="Look Up Evidence", slot="center_top"),
                StudyVisualObject(id="source", kind="book", label="Source Material", slot="center_bottom"),
                StudyVisualObject(id="answer", kind="answer_panel", label="Source-backed Answer", slot="right_mid", detail=["Cited source"]),
            ]
            beats = [
                StudyVisualBeat(cue="question", action="reveal", target="question"),
                StudyVisualBeat(cue="look", action="send", target="question", source="question", destination="retriever", label="question", weight=2),
                StudyVisualBeat(cue="source", action="reveal", target="source"),
                StudyVisualBeat(cue="answer", action="stream", target="answer", source="source", weight=3),
                StudyVisualBeat(cue="source", action="connect", target="answer", source="answer", destination="source", weight=2),
            ]
            return finish(purpose="Complete the analogy with the technical behavior: look up a source, then answer from it.", layout="browser_demo", objects=objects, beats=beats, env="browser_space", camera="follow")

        if "step-by-step system architecture and data flow" in base_title:
            if part == 1:
                objects = [
                    StudyVisualObject(id="doc", kind="document", label="Source Document", slot="left_mid"),
                    StudyVisualObject(id="chunks", kind="array", label="Chunks", slot="center_top", detail=["Chunk 1", "Chunk 2", "Chunk 3"]),
                    StudyVisualObject(id="space", kind="point_cloud", label="Embedding Space", slot="center_bottom"),
                    StudyVisualObject(id="store", kind="vector_store", label="Vector Store", slot="right_mid"),
                ]
                beats = [
                    StudyVisualBeat(cue="document", action="reveal", target="doc"),
                    StudyVisualBeat(cue="chunk", action="split", target="chunks", source="doc", weight=3),
                    StudyVisualBeat(cue="embedding", action="transform", target="space", source="chunks", weight=3),
                    StudyVisualBeat(cue="store", action="send", target="space", source="space", destination="store", label="vectors", weight=2),
                ]
                return finish(purpose="Show ingestion as a physical sequence: document → chunks → embedding space → vector store.", layout="left_to_right", objects=objects, beats=beats, env="document_space", camera="follow", motion="high")
            if part == 2:
                objects = [
                    StudyVisualObject(id="question", kind="search_ui", label="Question", slot="left_top"),
                    StudyVisualObject(id="qvec", kind="vector", label="Query Vector", slot="left_bottom"),
                    StudyVisualObject(id="space", kind="point_cloud", label="Semantic Search", slot="center"),
                    StudyVisualObject(id="match", kind="document", label="Top Match", slot="right_mid"),
                ]
                beats = [
                    StudyVisualBeat(cue="query", action="reveal", target="question"),
                    StudyVisualBeat(cue="vector", action="transform", target="qvec", source="question", weight=2),
                    StudyVisualBeat(cue="search", action="scan", target="space", source="qvec", weight=3),
                    StudyVisualBeat(cue="relevant", action="select", target="match", source="space", weight=2),
                ]
                return finish(purpose="Show retrieval as a visual nearest-neighbor search, not another retriever box.", layout="array_trace", objects=objects, beats=beats, pattern="retrieval_match", env="data_space", camera="follow", motion="high")
            objects = [
                StudyVisualObject(id="match", kind="document", label="Top Retrieved Match", slot="left_top"),
                StudyVisualObject(id="question", kind="search_ui", label="Original Question", slot="left_bottom"),
                StudyVisualObject(id="context", kind="context_window", label="Question + Evidence", slot="center", detail=["Question", "Top passage"]),
                StudyVisualObject(id="model", kind="model", label="Language Model", slot="right_top"),
                StudyVisualObject(id="answer", kind="answer_panel", label="Generated Answer", slot="right_bottom", detail=["Source 1"]),
            ]
            beats = [
                StudyVisualBeat(cue="retrieved", action="reveal", target="match"),
                StudyVisualBeat(cue="question", action="reveal", target="question"),
                StudyVisualBeat(cue="context", action="merge", target="context", source="match", weight=3),
                StudyVisualBeat(cue="context", action="connect", target="context", source="question", destination="context", label="question", weight=2),
                StudyVisualBeat(cue="model", action="send", target="context", source="context", destination="model", label="context", weight=2),
                StudyVisualBeat(cue="generate", action="stream", target="answer", source="model", weight=3),
            ]
            return finish(purpose="Carry the retrieved match into the next step: combine it with the original question, then generate the answer from that context.", layout="freeform", objects=objects, beats=beats, env="data_space", camera="follow", motion="high")

        if "translating the architecture into code" in base_title:
            variants = {
                1: (["qvec = embed(query)", "docs = search(qvec, k=3)"], "Semantic Matches", "Top Documents", "point_cloud", "document"),
                2: (["context = join(docs)", "prompt = build(query, context)"], "Retrieved Docs", "Context Window", "document", "context_window"),
                3: (["answer = llm(prompt)", "return answer"], "Language Model", "Generated Answer", "model", "answer_panel"),
                4: (["score = grounded(answer, docs)", "assert score >= threshold"], "Source Evidence", "Grounding Check", "document", "shield"),
            }
            code_lines, left_label, right_label, left_kind, right_kind = variants.get(part, variants[4])
            objects = [
                StudyVisualObject(id="code", kind="code", label=f"Step {part}", slot="wide_mid", detail=code_lines),
                StudyVisualObject(id="state", kind=left_kind, label=left_label, slot="right_top"),
                StudyVisualObject(id="result", kind=right_kind, label=right_label, slot="right_bottom", detail=["Source 1"] if right_kind in {"context_window", "answer_panel"} else []),
            ]
            beats = [
                StudyVisualBeat(cue="code", action="type_code", target="code"),
                StudyVisualBeat(cue="first", action="step_code", target="code", weight=2),
                StudyVisualBeat(cue="result", action="reveal", target="state"),
                StudyVisualBeat(cue="next", action="step_code", target="code", weight=2),
                StudyVisualBeat(cue="output", action="reveal", target="result"),
                StudyVisualBeat(cue="verify", action="select", target="result", weight=2),
            ]
            return finish(purpose=f"Execute code step {part} and connect each line to the state it creates.", layout="code_plus_state", objects=objects, beats=beats, pattern="worked_example", env="code_lab", camera="focus", motion="high")

        if "verifying your pipeline" in base_title and "failure" in base_title:
            if part == 1:
                objects = [
                    StudyVisualObject(id="query", kind="search_ui", label="Test Query", slot="left_top"),
                    StudyVisualObject(id="expected", kind="document", label="Expected Evidence", slot="left_bottom"),
                    StudyVisualObject(id="retrieved", kind="point_cloud", label="Retrieved Matches", slot="center"),
                    StudyVisualObject(id="score", kind="table", label="Retrieval Check", slot="right_mid"),
                ]
                beats = [
                    StudyVisualBeat(cue="test", action="reveal", target="query"),
                    StudyVisualBeat(cue="expected", action="reveal", target="expected"),
                    StudyVisualBeat(cue="retrieval", action="scan", target="retrieved", source="query", weight=3),
                    StudyVisualBeat(cue="compare", action="compare", target="score", source="retrieved", destination="expected", weight=2),
                ]
                return finish(purpose="Verify retrieval separately before judging the generated answer.", layout="table_focus", objects=objects, beats=beats, pattern="verification", env="data_space", camera="guided")
            if part == 2:
                objects = [
                    StudyVisualObject(id="answer", kind="answer_panel", label="Model Answer", slot="left_top", detail=["Claim A", "Claim B"]),
                    StudyVisualObject(id="source", kind="document", label="Source Evidence", slot="left_bottom"),
                    StudyVisualObject(id="gate", kind="gate", label="Evidence Check", slot="center"),
                    StudyVisualObject(id="pass", kind="shield", label="Supported", slot="right_top"),
                    StudyVisualObject(id="fail", kind="resource", label="Unsupported", slot="right_bottom"),
                ]
                beats = [
                    StudyVisualBeat(cue="answer", action="reveal", target="answer"),
                    StudyVisualBeat(cue="evidence", action="reveal", target="source"),
                    StudyVisualBeat(cue="compare", action="compare", target="gate", source="answer", destination="source", weight=2),
                    StudyVisualBeat(cue="supported", action="allow", target="gate", source="answer", destination="pass", label="SUPPORTED", weight=2),
                    StudyVisualBeat(cue="unsupported", action="reject", target="gate", source="answer", destination="fail", label="UNSUPPORTED", weight=2),
                ]
                return finish(purpose="Trace answer claims back to evidence and visibly separate supported from unsupported output.", layout="boundary", objects=objects, beats=beats, pattern="verification", env="security_boundary", camera="focus", motion="high")
            objects = [
                StudyVisualObject(id="good_source", kind="document", label="Relevant Evidence", slot="left_top"),
                StudyVisualObject(id="good_answer", kind="answer_panel", label="Grounded Result", slot="right_top", detail=["Source cited"]),
                StudyVisualObject(id="weak_source", kind="document", label="Weak Evidence", slot="left_bottom"),
                StudyVisualObject(id="weak_answer", kind="answer_panel", label="Weak Result", slot="right_bottom", detail=["No support"]),
            ]
            beats = [
                StudyVisualBeat(cue="relevant", action="reveal", target="good_source"),
                StudyVisualBeat(cue="answer", action="stream", target="good_answer", source="good_source", weight=2),
                StudyVisualBeat(cue="weak", action="reveal", target="weak_source"),
                StudyVisualBeat(cue="failure", action="stream", target="weak_answer", source="weak_source", weight=2),
                StudyVisualBeat(cue="quality", action="compare", target="good_answer", source="good_answer", destination="weak_answer", weight=2),
            ]
            return finish(purpose="Make the failure case causal: weak retrieval produces a weak answer even when generation still runs.", layout="split", objects=objects, beats=beats, pattern="compare_paths", env="document_space", camera="guided")

        if "tradeoffs and practical takeaways" in base_title:
            lower = narration.lower()
            if "latency" in lower or "slower" in lower or "speed" in lower:
                objects = [
                    StudyVisualObject(id="direct", kind="model", label="Direct Generation", slot="left_top"),
                    StudyVisualObject(id="rag", kind="vector_store", label="Retrieve First", slot="left_bottom"),
                    StudyVisualObject(id="latency", kind="chart", label="Response Time", slot="center"),
                    StudyVisualObject(id="quality", kind="answer_panel", label="Grounding Benefit", slot="right_mid", detail=["Source backed"]),
                ]
                beats = [
                    StudyVisualBeat(cue="latency", action="reveal", target="latency"),
                    StudyVisualBeat(cue="retrieval", action="reveal", target="rag"),
                    StudyVisualBeat(cue="generation", action="reveal", target="direct"),
                    StudyVisualBeat(cue="tradeoff", action="compare", target="latency", source="direct", destination="rag", weight=2),
                    StudyVisualBeat(cue="quality", action="select", target="quality", weight=2),
                ]
                return finish(purpose="Show the latency-versus-grounding tradeoff with a concrete comparison.", layout="table_focus", objects=objects, beats=beats, pattern="compare_paths", env="clean_light", camera="focus")
            if "fresh" in lower or "update" in lower or "current" in lower or "stale" in lower:
                objects = [
                    StudyVisualObject(id="memory", kind="model", label="Model Memory", slot="left_top"),
                    StudyVisualObject(id="fresh", kind="book", label="Updated Sources", slot="left_bottom"),
                    StudyVisualObject(id="context", kind="context_window", label="Fresh Context", slot="right_top", detail=["Latest source"]),
                    StudyVisualObject(id="answer", kind="answer_panel", label="Current Answer", slot="right_bottom", detail=["Source cited"]),
                ]
                beats = [
                    StudyVisualBeat(cue="model", action="reveal", target="memory"),
                    StudyVisualBeat(cue="fresh", action="reveal", target="fresh"),
                    StudyVisualBeat(cue="context", action="transform", target="context", source="fresh", weight=2),
                    StudyVisualBeat(cue="answer", action="stream", target="answer", source="context", weight=3),
                ]
                return finish(purpose="Show why external sources can refresh an answer without retraining the model.", layout="split", objects=objects, beats=beats, pattern="compare_paths", env="document_space", camera="guided")
            objects = [
                StudyVisualObject(id="sources", kind="document", label="Source Quality", slot="left_mid"),
                StudyVisualObject(id="retrieval", kind="point_cloud", label="Retrieval Quality", slot="center"),
                StudyVisualObject(id="answer", kind="answer_panel", label="Answer Quality", slot="right_mid", detail=["Evidence linked"]),
            ]
            beats = [
                StudyVisualBeat(cue="source", action="reveal", target="sources"),
                StudyVisualBeat(cue="retrieval", action="scan", target="retrieval", source="sources", weight=2),
                StudyVisualBeat(cue="quality", action="compare", target="answer", source="retrieval", destination="answer", weight=2),
                StudyVisualBeat(cue="answer", action="stream", target="answer", source="retrieval", weight=2),
            ]
            return finish(purpose="Keep the practical takeaway causal: source quality influences retrieval, which influences answer quality.", layout="left_to_right", objects=objects, beats=beats, pattern="compare_paths", env="data_space", camera="follow")

        if base_title == "what it means":
            objects = [
                StudyVisualObject(id="plain_model", kind="model", label="Model Alone", slot="left_top"),
                StudyVisualObject(id="plain_answer", kind="answer_panel", label="Memory-only Answer", slot="left_bottom", detail=["No source"]),
                StudyVisualObject(id="context", kind="context_window", label="Retrieved Context", slot="right_top", detail=["Relevant evidence"]),
                StudyVisualObject(id="grounded", kind="answer_panel", label="Grounded Answer", slot="right_bottom", detail=["Source cited"]),
            ]
            beats = [
                StudyVisualBeat(cue="model", action="reveal", target="plain_model"),
                StudyVisualBeat(cue="answer", action="stream", target="plain_answer", source="plain_model", weight=2),
                StudyVisualBeat(cue="context", action="reveal", target="context"),
                StudyVisualBeat(cue="grounded", action="stream", target="grounded", source="context", weight=3),
                StudyVisualBeat(cue="difference", action="compare", target="grounded", source="plain_answer", destination="grounded", weight=2),
            ]
            return finish(purpose="End with the simplest mental contrast: model memory alone versus model plus retrieved evidence.", layout="split", objects=objects, beats=beats, pattern="recap", env="clean_light", camera="focus")

        # “What to Watch Next” is a call-to-action/continuation scene, not a license
        # to redraw the RAG pipeline. Let the narration-specific storyboard survive
        # so the ending illustrates exactly the next action/topic that is spoken.
        if base_title == "what to watch next":
            return None

        return None

    @staticmethod
    def _is_agent_topic(text: str) -> bool:
        lower = text.lower()
        return any(term in lower for term in ("ai agent", "ai agents", "agentic ai", "agentic workflow"))

    @classmethod
    def _agent_chapter_storyboard(
        cls,
        sb: StudySceneStoryboard,
        *,
        scene: object,
        topic: str,
    ) -> StudySceneStoryboard | None:
        """Content-first visual profile for AI-agent lessons.

        The v0.9 output showed that a generic technical fallback can turn an
        agent lesson into repeated circles, gates and code panes. This profile
        chooses a visual grammar from the narrated *teaching job* so each
        chapter answers one learner question.
        """
        title = str(getattr(scene, "title", ""))
        narration = str(getattr(scene, "description", ""))
        scene_id = int(getattr(scene, "id"))
        lower = f"{title} {narration}".lower()
        base_title = title.split("—", 1)[0].strip().lower()

        def has(*terms: str) -> bool:
            return any(term in lower for term in terms)

        def finish(*, purpose: str, layout: str, objects: list[StudyVisualObject], beats: list[StudyVisualBeat], pattern: str = "progressive_flow", env: str = "technical", camera: str = "guided") -> StudySceneStoryboard:
            return sb.model_copy(update={
                "purpose": purpose,
                "layout": layout,
                "objects": objects,
                "beats": beats,
                "teaching_pattern": pattern,
                "reference_keywords": [obj.label for obj in objects[:5]],
                "environment": env,
                "camera_style": camera,
            })

        if scene_id == 1 or base_title in {"context", "plain-language definition"} and has("goal", "task"):
            objects = [
                StudyVisualObject(id="goal", kind="search_ui", label="User Goal", slot="left_mid", detail=["Complete a multi-step task"]),
                StudyVisualObject(id="agent", kind="agent", label="AI Agent", slot="center"),
                StudyVisualObject(id="tool", kind="tool", label="Selected Tool", slot="right_top"),
                StudyVisualObject(id="result", kind="answer_panel", label="Completed Result", slot="right_bottom", detail=["Task outcome"]),
            ]
            beats = [
                StudyVisualBeat(cue="goal", action="reveal", target="goal"),
                StudyVisualBeat(cue="agent", action="send", target="goal", source="goal", destination="agent", weight=2),
                StudyVisualBeat(cue="tool", action="select", target="tool", source="agent", weight=2),
                StudyVisualBeat(cue="action", action="send", target="tool", source="agent", destination="tool", weight=2),
                StudyVisualBeat(cue="complete", action="stream", target="result", source="tool", weight=2),
            ]
            return finish(
                purpose="Establish the difference between a user goal and an agent that takes actions to complete it.",
                layout="browser_demo", objects=objects, beats=beats,
                pattern="problem_solution", env="browser_space", camera="follow",
            )

        if has("doesn't just respond", "does not just respond", "plans and acts", "plain-language", "language model to decide"):
            objects = [
                StudyVisualObject(id="prompt", kind="search_ui", label="User Request", slot="left_mid"),
                StudyVisualObject(id="chatbot", kind="model", label="Chatbot", slot="center_top"),
                StudyVisualObject(id="agent", kind="agent", label="Agent", slot="center_bottom"),
                StudyVisualObject(id="tool", kind="tool", label="External Tool", slot="right_top"),
                StudyVisualObject(id="outcome", kind="answer_panel", label="Task Outcome", slot="right_bottom"),
            ]
            beats = [
                StudyVisualBeat(cue="request", action="reveal", target="prompt"),
                StudyVisualBeat(cue="respond", action="send", target="chatbot", source="prompt", destination="chatbot", weight=2),
                StudyVisualBeat(cue="agent", action="reveal", target="agent"),
                StudyVisualBeat(cue="tool", action="select", target="tool", source="agent", weight=2),
                StudyVisualBeat(cue="complete", action="stream", target="outcome", source="tool", weight=2),
            ]
            return finish(
                purpose="Contrast one-shot response generation with an agent that can act through tools.",
                layout="split", objects=objects, beats=beats,
                pattern="compare_paths", env="clean_light", camera="focus",
            )

        if has("mcp", "model context protocol", "connector", "standard interface"):
            objects = [
                StudyVisualObject(id="agent", kind="agent", label="AI Agent", slot="left_mid"),
                StudyVisualObject(id="mcp", kind="connector", label="MCP Interface", slot="center"),
                StudyVisualObject(id="tools", kind="tool", label="Tools", slot="right_top"),
                StudyVisualObject(id="data", kind="resource", label="Data / Apps", slot="right_bottom"),
            ]
            beats = [
                StudyVisualBeat(cue="agent", action="reveal", target="agent"),
                StudyVisualBeat(cue="mcp", action="reveal", target="mcp"),
                StudyVisualBeat(cue="tools", action="connect", target="tools", source="agent", destination="mcp", weight=2),
                StudyVisualBeat(cue="data", action="connect", target="data", source="mcp", destination="data", weight=2),
                StudyVisualBeat(cue="result", action="return", target="data", source="data", destination="agent", weight=2),
            ]
            return finish(
                purpose="Show MCP as the standard connection layer between an agent and external capabilities.",
                layout="left_to_right", objects=objects, beats=beats,
                env="technical", camera="follow",
            )

        if has("multi-agent", "multiple agents", "researcher agent", "writer agent", "reviewer agent"):
            objects = [
                StudyVisualObject(id="manager", kind="agent", label="Coordinator", slot="left_mid"),
                StudyVisualObject(id="researcher", kind="agent", label="Research Agent", slot="center_top"),
                StudyVisualObject(id="writer", kind="agent", label="Writer Agent", slot="center_bottom"),
                StudyVisualObject(id="artifact", kind="document", label="Shared Artifact", slot="right_mid"),
            ]
            beats = [
                StudyVisualBeat(cue="agent", action="reveal", target="manager"),
                StudyVisualBeat(cue="research", action="send", target="researcher", source="manager", destination="researcher", weight=2),
                StudyVisualBeat(cue="result", action="return", target="artifact", source="researcher", destination="artifact", weight=2),
                StudyVisualBeat(cue="writer", action="send", target="writer", source="artifact", destination="writer", weight=2),
                StudyVisualBeat(cue="final", action="return", target="artifact", source="writer", destination="manager", weight=2),
            ]
            return finish(
                purpose="Show multiple agents collaborating by handing a concrete artifact between roles.",
                layout="freeform", objects=objects, beats=beats,
                env="document_space", camera="follow",
            )

        if has("memory", "context window", "current context", "persistent memory", "temporary buffer"):
            objects = [
                StudyVisualObject(id="context", kind="context_window", label="Current Context", slot="left_mid", detail=["Goal", "Tool result"]),
                StudyVisualObject(id="memory", kind="resource", label="Optional Memory", slot="left_bottom"),
                StudyVisualObject(id="agent", kind="agent", label="Agent", slot="center"),
                StudyVisualObject(id="decision", kind="answer_panel", label="Next Decision", slot="right_mid", detail=["Use what matters now"]),
            ]
            beats = [
                StudyVisualBeat(cue="context", action="reveal", target="context"),
                StudyVisualBeat(cue="memory", action="reveal", target="memory"),
                StudyVisualBeat(cue="agent", action="merge", target="agent", source="context", weight=2),
                StudyVisualBeat(cue="decision", action="stream", target="decision", source="agent", weight=2),
            ]
            return finish(
                purpose="Separate current working context from optional persistent memory and show how they inform the next decision.",
                layout="freeform", objects=objects, beats=beats,
                pattern="context_build", env="document_space", camera="guided",
            )

        if has("weather", "api", "tool selection", "selects a tool", "picks tools", "search tool", "database") and not has("permission", "unsafe"):
            objects = [
                StudyVisualObject(id="request", kind="search_ui", label="User Request", slot="left_mid"),
                StudyVisualObject(id="agent", kind="agent", label="Agent", slot="center"),
                StudyVisualObject(id="tool", kind="tool", label="Chosen Tool", slot="right_top"),
                StudyVisualObject(id="api", kind="api", label="Tool Call", slot="right_mid"),
                StudyVisualObject(id="answer", kind="answer_panel", label="Verified Response", slot="right_bottom"),
            ]
            beats = [
                StudyVisualBeat(cue="input", action="reveal", target="request"),
                StudyVisualBeat(cue="agent", action="send", target="agent", source="request", destination="agent", weight=2),
                StudyVisualBeat(cue="tool", action="select", target="tool", source="agent", weight=2),
                StudyVisualBeat(cue="request", action="send", target="api", source="tool", destination="api", weight=2),
                StudyVisualBeat(cue="returns", action="return", target="answer", source="api", destination="agent", weight=2),
            ]
            return finish(
                purpose="Make tool selection concrete: request -> agent decision -> selected capability -> returned result.",
                layout="browser_demo", objects=objects, beats=beats,
                pattern="worked_example", env="browser_space", camera="follow",
            )

        if has("cycle", "loop", "observes", "observe", "goal is met", "checks if the goal", "next action", "until completion"):
            objects = [
                StudyVisualObject(id="goal", kind="prompt", label="Goal", slot="left_mid"),
                StudyVisualObject(id="agent", kind="agent", label="Decide", slot="center"),
                StudyVisualObject(id="tool", kind="tool", label="Act", slot="right_top"),
                StudyVisualObject(id="observation", kind="resource", label="Observe Result", slot="right_bottom"),
                StudyVisualObject(id="check", kind="gate", label="Goal Complete?", slot="center_bottom"),
            ]
            beats = [
                StudyVisualBeat(cue="goal", action="reveal", target="goal"),
                StudyVisualBeat(cue="decide", action="send", target="agent", source="goal", destination="agent", weight=2),
                StudyVisualBeat(cue="tool", action="send", target="tool", source="agent", destination="tool", weight=2),
                StudyVisualBeat(cue="observe", action="return", target="observation", source="tool", destination="agent", weight=2),
                StudyVisualBeat(cue="goal", action="compare", target="check", source="observation", destination="check", weight=2),
            ]
            return finish(
                purpose="Show the agent loop as a feedback cycle: decide, act, observe, check completion, then continue only if needed.",
                layout="radial", objects=objects, beats=beats,
                env="data_space", camera="follow",
            )

        if has("malformed", "invalid argument", "missing filename", "argument parsing", "ambiguous", "empty input"):
            objects = [
                StudyVisualObject(id="cases", kind="table", label="Input Cases", slot="left_mid"),
                StudyVisualObject(id="validator", kind="gate", label="Argument Check", slot="center"),
                StudyVisualObject(id="valid", kind="badge", label="Valid Args", slot="right_top"),
                StudyVisualObject(id="error", kind="answer_panel", label="Clear Error", slot="right_bottom", detail=["Do not execute"]),
            ]
            beats = [
                StudyVisualBeat(cue="input", action="reveal", target="cases"),
                StudyVisualBeat(cue="parse", action="send", target="validator", source="cases", destination="validator", weight=2),
                StudyVisualBeat(cue="valid", action="allow", target="validator", source="cases", destination="valid", label="VALID", weight=2),
                StudyVisualBeat(cue="invalid", action="reject", target="validator", source="cases", destination="error", label="ERROR", weight=2),
            ]
            return finish(
                purpose="Test argument parsing with valid and invalid cases, showing that invalid input stops before tool execution.",
                layout="table_focus", objects=objects, beats=beats,
                pattern="verification", env="clean_light", camera="focus",
            )

        if has("permission", "private file", "/root", "deletion rights", "unauthorized", "sensitive"):
            objects = [
                StudyVisualObject(id="request", kind="search_ui", label="Sensitive Request", slot="left_mid"),
                StudyVisualObject(id="boundary", kind="shield", label="Permission Check", slot="center"),
                StudyVisualObject(id="allowed", kind="resource", label="Allowed Resource", slot="right_top"),
                StudyVisualObject(id="denied", kind="answer_panel", label="Access Denied", slot="right_bottom", detail=["No tool execution"]),
            ]
            beats = [
                StudyVisualBeat(cue="access", action="reveal", target="request"),
                StudyVisualBeat(cue="permission", action="send", target="boundary", source="request", destination="boundary", weight=2),
                StudyVisualBeat(cue="access", action="allow", target="boundary", source="request", destination="allowed", label="ALLOW", weight=2),
                StudyVisualBeat(cue="lacks access", action="reject", target="boundary", source="request", destination="denied", label="DENY", weight=2),
            ]
            return finish(
                purpose="Use one dedicated permission scene to show where unauthorized actions are stopped.",
                layout="boundary", objects=objects, beats=beats,
                pattern="verification", env="security_boundary", camera="focus",
            )

        if has("tool overuse", "same tool repeatedly", "without progress", "looping", "stops mid-task", "completion check", "incomplete workflow"):
            objects = [
                StudyVisualObject(id="agent", kind="agent", label="Agent", slot="left_mid"),
                StudyVisualObject(id="tool", kind="tool", label="Repeated Tool", slot="center_top"),
                StudyVisualObject(id="progress", kind="chart", label="Progress", slot="right_top"),
                StudyVisualObject(id="stop", kind="gate", label="Stop / Retry Rule", slot="center_bottom"),
                StudyVisualObject(id="result", kind="answer_panel", label="Explicit Failure", slot="right_bottom", detail=["No silent stop"]),
            ]
            beats = [
                StudyVisualBeat(cue="tool", action="send", target="tool", source="agent", destination="tool", weight=2),
                StudyVisualBeat(cue="repeatedly", action="return", target="agent", source="tool", destination="agent", weight=2),
                StudyVisualBeat(cue="progress", action="compare", target="progress", source="tool", destination="progress", weight=2),
                StudyVisualBeat(cue="completion", action="select", target="stop", weight=2),
                StudyVisualBeat(cue="failure", action="stream", target="result", source="stop", weight=2),
            ]
            return finish(
                purpose="Show a no-progress loop and the completion/stop rule that prevents endless tool calls.",
                layout="freeform", objects=objects, beats=beats,
                pattern="verification", env="data_space", camera="follow",
            )

        if "verification" in base_title or has("test", "testing", "verify", "evaluation"):
            objects = [
                StudyVisualObject(id="matrix", kind="table", label="Agent Test Matrix", slot="left_mid"),
                StudyVisualObject(id="tool", kind="tool", label="Tool Choice", slot="center_top"),
                StudyVisualObject(id="order", kind="array", label="Action Order", slot="center_bottom", detail=["1", "2", "3"]),
                StudyVisualObject(id="result", kind="answer_panel", label="Expected Outcome", slot="right_mid", detail=["Pass / clear failure"]),
            ]
            beats = [
                StudyVisualBeat(cue="test", action="reveal", target="matrix"),
                StudyVisualBeat(cue="tool", action="select", target="tool", weight=2),
                StudyVisualBeat(cue="ordering", action="scan", target="order", weight=2),
                StudyVisualBeat(cue="completion", action="compare", target="result", source="order", destination="result", weight=2),
            ]
            return finish(
                purpose="Evaluate agent behavior across tool choice, argument/action order and completion outcome.",
                layout="table_focus", objects=objects, beats=beats,
                pattern="verification", env="clean_light", camera="focus",
            )

        if "tradeoff" in base_title or has("tradeoff", "capability", "risk", "complexity", "predictably"):
            objects = [
                StudyVisualObject(id="balance", kind="balance", label="Capability vs Control", slot="center_top"),
                StudyVisualObject(id="tools", kind="tool", label="More Tool Access", slot="left_mid"),
                StudyVisualObject(id="memory", kind="context_window", label="More Context / Memory", slot="right_mid"),
                StudyVisualObject(id="guard", kind="shield", label="Validation & Limits", slot="center_bottom"),
            ]
            beats = [
                StudyVisualBeat(cue="tool access", action="reveal", target="tools"),
                StudyVisualBeat(cue="memory", action="reveal", target="memory"),
                StudyVisualBeat(cue="risk", action="compare", target="balance", source="tools", destination="memory", weight=2),
                StudyVisualBeat(cue="validation", action="select", target="guard", weight=2),
            ]
            return finish(
                purpose="Summarize agent-design tradeoffs without turning every risk into another permission gate.",
                layout="split", objects=objects, beats=beats,
                pattern="compare_paths", env="clean_light", camera="focus",
            )

        if has("python", "code", "function", "dictionary", "callable") or "implementation" in base_title:
            # Use code only when the narration is actually mapping the mental model
            # to code; otherwise show live state beside the minimal snippet.
            code_lines = [
                "tool = select_tool(request)",
                "result = tool(**args)",
                "state = observe(result)",
                "return finish_or_continue(state)",
            ]
            if has("dictionary", "available tools"):
                code_lines = [
                    "tools = {\"search\": search, \"weather\": weather}",
                    "tool = select_tool(request, tools)",
                    "result = tool(**args)",
                    "return result",
                ]
            objects = [
                StudyVisualObject(id="code", kind="code", label="Agent Loop", slot="wide_mid", detail=code_lines),
                StudyVisualObject(id="tool", kind="tool", label="Selected Tool", slot="right_top"),
                StudyVisualObject(id="state", kind="answer_panel", label="Observed State", slot="right_bottom", detail=["continue / finish"]),
            ]
            beats = [
                StudyVisualBeat(cue="code", action="type_code", target="code"),
                StudyVisualBeat(cue="tool", action="step_code", target="code", weight=2),
                StudyVisualBeat(cue="tool", action="reveal", target="tool"),
                StudyVisualBeat(cue="result", action="step_code", target="code", weight=2),
                StudyVisualBeat(cue="state", action="stream", target="state", source="tool", weight=2),
            ]
            return finish(
                purpose="Map the agent mental model to the smallest code needed, while showing the live tool/state consequence.",
                layout="code_plus_state", objects=objects, beats=beats,
                pattern="worked_example", env="code_lab", camera="focus",
            )

        if base_title == "what it means" or has("recap", "in short", "work best", "predictably"):
            objects = [
                StudyVisualObject(id="goal", kind="prompt", label="Goal", slot="left_mid"),
                StudyVisualObject(id="agent", kind="agent", label="Agent", slot="center"),
                StudyVisualObject(id="tools", kind="tool", label="Tools", slot="right_top"),
                StudyVisualObject(id="result", kind="answer_panel", label="Verified Outcome", slot="right_bottom", detail=["Complete or clear failure"]),
            ]
            beats = [
                StudyVisualBeat(cue="goal", action="reveal", target="goal"),
                StudyVisualBeat(cue="agent", action="send", target="agent", source="goal", destination="agent", weight=2),
                StudyVisualBeat(cue="tools", action="send", target="tools", source="agent", destination="tools", weight=2),
                StudyVisualBeat(cue="result", action="return", target="result", source="tools", destination="agent", weight=2),
            ]
            return finish(
                purpose="End on the compact agent mental model: goal, decision, tool action and verified outcome.",
                layout="left_to_right", objects=objects, beats=beats,
                pattern="recap", env="clean_light", camera="guided",
            )

        return None

    @classmethod
    def _repair_topic_specific_teaching(
        cls,
        sb: StudySceneStoryboard,
        scene: object,
        topic: str,
    ) -> StudySceneStoryboard:
        """Enforce topic-specific visual operations where generic diagrams fail.

        RAG is the first strict profile because it exposed the repeated
        box-arrow problem in real output. The same finite DSL remains in use.
        """
        title = str(getattr(scene, "title", ""))
        narration = str(getattr(scene, "description", ""))
        scene_text = f"{title} {narration}".lower()
        domain_text = f"{topic} {scene_text}"

        if cls._is_agent_topic(domain_text):
            agent_board = cls._agent_chapter_storyboard(sb, scene=scene, topic=topic)
            if agent_board is not None:
                return agent_board

        if not cls._is_rag_text(domain_text):
            return sb

        sid = int(getattr(scene, "id"))
        title_lower = title.lower()
        has = lambda *terms: any(term in scene_text for term in terms)

        chapter_storyboard = cls._rag_chapter_storyboard(
            sb, title=title, narration=narration, scene_id=sid
        )
        if chapter_storyboard is not None:
            return chapter_storyboard

        if has("recap", "summary", "takeaway", "remember", "in short", "wrap up", "what you learned"):
            objects = [
                StudyVisualObject(id="query", kind="prompt", label="Query", slot="left_mid"),
                StudyVisualObject(id="retrieve", kind="vector_store", label="Retrieve", slot="center_top"),
                StudyVisualObject(id="augment", kind="prompt", label="Augment", slot="center"),
                StudyVisualObject(id="generate", kind="model", label="Generate", slot="right_top"),
                StudyVisualObject(id="verify", kind="shield", label="Verify", slot="right_mid"),
            ]
            beats = [
                StudyVisualBeat(cue="query", action="reveal", target="query"),
                StudyVisualBeat(cue="retrieve", action="send", target="query", source="query", destination="retrieve", weight=2),
                StudyVisualBeat(cue="context", action="transform", target="augment", source="retrieve", weight=2),
                StudyVisualBeat(cue="generate", action="send", target="augment", source="augment", destination="generate", weight=2),
                StudyVisualBeat(cue="verify", action="transform", target="verify", source="generate", weight=2),
            ]
            return sb.model_copy(update={
                "purpose": "Consolidate the RAG mental model without introducing a new abstraction.",
                "layout": "timeline",
                "objects": objects,
                "beats": beats,
                "teaching_pattern": "recap",
                "reference_keywords": ["RAG query retrieve augment generate verify"],
            })

        if sid == 1:
            objects = [
                StudyVisualObject(id="query", kind="prompt", label="User Question", slot="left_top"),
                StudyVisualObject(id="model", kind="model", label="Language Model", slot="center_top"),
                StudyVisualObject(id="docs", kind="document", label="Private Data", slot="left_bottom"),
                StudyVisualObject(id="answer", kind="resource", label="Grounded Answer", slot="right_mid"),
            ]
            beats = [
                StudyVisualBeat(cue="question", action="reveal", target="query"),
                StudyVisualBeat(cue="model", action="send", target="query", source="query", destination="model", weight=2),
                StudyVisualBeat(cue="data", action="reveal", target="docs"),
                StudyVisualBeat(cue="retrieve", action="send", target="docs", source="docs", destination="model", weight=2),
                StudyVisualBeat(cue="answer", action="transform", target="answer", source="model", weight=2),
            ]
            return sb.model_copy(update={
                "purpose": "Hook with the learner problem and show the concrete RAG payoff immediately.",
                "layout": "freeform", "objects": objects, "beats": beats,
                "teaching_pattern": "problem_solution",
                "reference_keywords": ["RAG private data grounded answer"],
            })


        if has("code", "python", "implement", "function", "python example"):
            objects = [
                StudyVisualObject(
                    id="code", kind="code", label="RAG Pipeline", slot="wide_mid",
                    detail=[
                        "docs = retrieve(query)",
                        "context = join(docs)",
                        "answer = generate(query, context)",
                        "verify(answer, docs)",
                    ],
                ),
                StudyVisualObject(id="docs", kind="document", label="Retrieved Docs", slot="right_top"),
                StudyVisualObject(id="answer", kind="resource", label="Grounded Answer", slot="right_bottom"),
            ]
            beats = [
                StudyVisualBeat(cue="retrieve", action="type_code", target="code"),
                StudyVisualBeat(cue="context", action="step_code", target="code", weight=2),
                StudyVisualBeat(cue="documents", action="reveal", target="docs"),
                StudyVisualBeat(cue="generate", action="step_code", target="code", weight=2),
                StudyVisualBeat(cue="answer", action="reveal", target="answer"),
                StudyVisualBeat(cue="verify", action="step_code", target="code", weight=2),
            ]
            return sb.model_copy(update={
                "purpose": "Execute the RAG pipeline line by line and show state changes.",
                "layout": "code_plus_state",
                "objects": objects,
                "beats": beats,
                "teaching_pattern": "worked_example",
                "reference_keywords": ["RAG Python retrieve context generate verify"],
                "environment": "code_lab",
                "camera_style": "focus",
            })

        if has("mental model", "architecture", "rag flow", "external documents"):
            objects = [
                StudyVisualObject(id="query", kind="search_ui", label="Question", slot="left_top"),
                StudyVisualObject(id="retriever", kind="vector_store", label="Retriever", slot="center_top"),
                StudyVisualObject(id="docs", kind="document", label="External Documents", slot="center_bottom"),
                StudyVisualObject(id="model", kind="model", label="Language Model", slot="right_top"),
                StudyVisualObject(id="answer", kind="answer_panel", label="Context-aware Answer", slot="right_bottom", detail=["Source cited"]),
            ]
            beats = [
                StudyVisualBeat(cue="query", action="reveal", target="query"),
                StudyVisualBeat(cue="external documents", action="reveal", target="docs"),
                StudyVisualBeat(cue="context", action="send", target="query", source="query", destination="retriever", weight=2),
                StudyVisualBeat(cue="documents", action="return", target="docs", source="retriever", destination="model", weight=2),
                StudyVisualBeat(cue="answer", action="transform", target="answer", source="model", weight=2),
            ]
            return sb.model_copy(update={
                "purpose": "Show the end-to-end RAG mental model as a changing request/context path.",
                "layout": "split", "objects": objects, "beats": beats,
                "teaching_pattern": "progressive_flow",
                "reference_keywords": ["RAG query retriever documents model answer"],
            })

        if has("embedding", "embeddings") and not has("similarity", "nearest"):
            objects = [
                StudyVisualObject(id="chunk", kind="document", label="Text Chunk", slot="left_mid"),
                StudyVisualObject(id="vector", kind="vector", label="Embedding Vector", slot="center"),
                StudyVisualObject(id="store", kind="vector_store", label="Vector Store", slot="right_mid"),
            ]
            beats = [
                StudyVisualBeat(cue="chunk", action="reveal", target="chunk"),
                StudyVisualBeat(cue="embedding", action="transform", target="vector", source="chunk", weight=2),
                StudyVisualBeat(cue="vector", action="highlight", target="vector"),
                StudyVisualBeat(cue="store", action="send", target="vector", source="vector", destination="store", weight=2),
            ]
            return sb.model_copy(update={
                "purpose": "Transform a text chunk into a vector and store it.",
                "layout": "left_to_right", "objects": objects, "beats": beats,
                "teaching_pattern": "progressive_flow",
                "reference_keywords": ["text embedding vector store"],
            })

        if has("chunking", "split document", "document chunks", "split a source document"):
            objects = [
                StudyVisualObject(id="doc", kind="document", label="Source Document", slot="left_mid"),
                StudyVisualObject(id="chunks", kind="array", label="Document Chunks", slot="center", detail=["Chunk 1", "Chunk 2", "Chunk 3"]),
                StudyVisualObject(id="focus", kind="document", label="Relevant Chunk", slot="right_mid"),
            ]
            beats = [
                StudyVisualBeat(cue="document", action="reveal", target="doc"),
                StudyVisualBeat(cue="chunk", action="split", target="chunks", source="doc", weight=3),
                StudyVisualBeat(cue="chunks", action="scan", target="chunks", weight=2),
                StudyVisualBeat(cue="relevant", action="select", target="focus", source="chunks", weight=2),
            ]
            return sb.model_copy(update={
                "purpose": "Physically split one source document into retrievable chunks.",
                "layout": "left_to_right", "objects": objects, "beats": beats,
                "teaching_pattern": "worked_example",
                "reference_keywords": ["document chunking chunks"],
                "environment": "document_space",
                "camera_style": "guided",
                "motion_density": "high",
            })



        if (("generate" in title_lower or "generation" in title_lower) or (has("generate", "generation") and not has("augment", "augmentation"))) and has("context", "retrieved", "grounded"):
            objects = [
                StudyVisualObject(id="prompt", kind="context_window", label="Augmented Context", slot="left_mid", detail=["Question", "Evidence"]),
                StudyVisualObject(id="model", kind="model", label="Language Model", slot="center"),
                StudyVisualObject(id="answer", kind="answer_panel", label="Generated Answer", slot="right_top", detail=["Source 1"]),
                StudyVisualObject(id="source", kind="document", label="Retrieved Source", slot="right_bottom"),
            ]
            beats = [
                StudyVisualBeat(cue="context", action="reveal", target="prompt"),
                StudyVisualBeat(cue="model", action="send", target="prompt", source="prompt", destination="model", weight=2),
                StudyVisualBeat(cue="generate", action="stream", target="answer", source="model", weight=3),
                StudyVisualBeat(cue="source", action="reveal", target="source"),
                StudyVisualBeat(cue="grounded", action="connect", target="answer", source="answer", destination="source", weight=2),
            ]
            return sb.model_copy(update={
                "purpose": "Generate the answer from augmented context and visibly link it to retrieved evidence.",
                "layout": "split", "objects": objects, "beats": beats,
                "teaching_pattern": "progressive_flow",
                "reference_keywords": ["RAG generation grounded answer source"],
                "environment": "data_space",
                "camera_style": "focus",
                "motion_density": "high",
            })

        if has("augment", "augmentation", "add context", "prompt context", "retrieved context", "context window"):
            objects = [
                StudyVisualObject(id="query", kind="search_ui", label="Question", slot="left_top"),
                StudyVisualObject(id="docs", kind="document", label="Retrieved Context", slot="left_bottom"),
                StudyVisualObject(id="prompt", kind="context_window", label="Augmented Context", slot="center", detail=["Question", "Evidence"]),
                StudyVisualObject(id="model", kind="model", label="Language Model", slot="right_mid"),
            ]
            beats = [
                StudyVisualBeat(cue="query", action="reveal", target="query"),
                StudyVisualBeat(cue="context", action="reveal", target="docs"),
                StudyVisualBeat(cue="augment", action="merge", target="prompt", source="docs", weight=3),
                StudyVisualBeat(cue="prompt", action="connect", target="prompt", source="query", destination="prompt", weight=2),
                StudyVisualBeat(cue="model", action="send", target="prompt", source="prompt", destination="model", weight=2),
            ]
            return sb.model_copy(update={
                "purpose": "Build the prompt by visibly combining the query with retrieved context.",
                "layout": "freeform", "objects": objects, "beats": beats,
                "teaching_pattern": "context_build",
                "reference_keywords": ["RAG augmented prompt retrieved context"],
                "environment": "document_space",
                "camera_style": "guided",
            })


        if has("limitation", "limitations", "depends on", "retrieval quality", "source quality"):
            objects = [
                StudyVisualObject(id="good", kind="document", label="Relevant Evidence", slot="left_top"),
                StudyVisualObject(id="poor", kind="document", label="Weak Evidence", slot="left_bottom"),
                StudyVisualObject(id="retrieval", kind="vector_store", label="Retrieval Quality", slot="center"),
                StudyVisualObject(id="answer", kind="resource", label="Answer Quality", slot="right_mid"),
            ]
            beats = [
                StudyVisualBeat(cue="retrieval quality", action="reveal", target="retrieval"),
                StudyVisualBeat(cue="source quality", action="reveal", target="good"),
                StudyVisualBeat(cue="source quality", action="reveal", target="poor"),
                StudyVisualBeat(cue="depends", action="compare", target="retrieval", source="good", destination="poor", weight=2),
                StudyVisualBeat(cue="answer", action="select", target="answer", weight=2),
            ]
            return sb.model_copy(update={
                "purpose": "Show how retrieval/source quality changes answer quality.",
                "layout": "split", "objects": objects, "beats": beats,
                "teaching_pattern": "compare_paths",
                "reference_keywords": ["RAG retrieval quality source quality answer"],
            })

        if has("test", "testing", "evaluate", "evaluation") and has("rag", "retrieval", "grounded", "answer"):
            objects = [
                StudyVisualObject(id="query", kind="prompt", label="Test Query", slot="left_top"),
                StudyVisualObject(id="expected", kind="document", label="Expected Evidence", slot="left_bottom"),
                StudyVisualObject(id="actual", kind="answer_panel", label="RAG Answer", slot="center", detail=["Source cited"]),
                StudyVisualObject(id="check", kind="gate", label="Quality Check", slot="right_mid"),
            ]
            beats = [
                StudyVisualBeat(cue="test", action="reveal", target="query"),
                StudyVisualBeat(cue="evidence", action="reveal", target="expected"),
                StudyVisualBeat(cue="answer", action="reveal", target="actual"),
                StudyVisualBeat(cue="evaluate", action="compare", target="check", source="actual", destination="expected", weight=2),
                StudyVisualBeat(cue="quality", action="select", target="check", weight=2),
            ]
            return sb.model_copy(update={
                "purpose": "Test retrieval and answer quality against expected evidence.",
                "layout": "split", "objects": objects, "beats": beats,
                "teaching_pattern": "verification",
                "reference_keywords": ["RAG test query evidence answer quality"],
            })

        if has("hallucination", "grounded", "verify", "verification", "faithful", "citation", "source-backed", "limitation"):
            objects = [
                StudyVisualObject(id="answer", kind="answer_panel", label="Model Answer", slot="left_top", detail=["Claim"]),
                StudyVisualObject(id="source", kind="document", label="Source Evidence", slot="left_bottom"),
                StudyVisualObject(id="gate", kind="gate", label="Evidence Check", slot="center"),
                StudyVisualObject(id="pass", kind="shield", label="Source-backed Answer", slot="right_top"),
                StudyVisualObject(id="fail", kind="resource", label="Unsupported Answer", slot="right_bottom"),
            ]
            beats = [
                StudyVisualBeat(cue="answer", action="reveal", target="answer"),
                StudyVisualBeat(cue="source", action="reveal", target="source"),
                StudyVisualBeat(cue="verify", action="compare", target="gate", source="answer", destination="source", weight=2),
                StudyVisualBeat(cue="grounded", action="allow", target="gate", source="answer", destination="pass", label="SUPPORTED", weight=2),
                StudyVisualBeat(cue="hallucination", action="reject", target="gate", source="answer", destination="fail", label="UNSUPPORTED", weight=2),
            ]
            return sb.model_copy(update={
                "purpose": "Contrast source-backed and unsupported answers through an evidence gate.",
                "layout": "boundary", "objects": objects, "beats": beats,
                "teaching_pattern": "verification",
                "reference_keywords": ["RAG evidence verification grounded hallucination"],
            })



        if has("similarity", "nearest", "retrieve", "retrieval", "search", "query vector"):
            objects = [
                StudyVisualObject(id="query", kind="search_ui", label="Question", slot="left_top"),
                StudyVisualObject(id="qvec", kind="vector", label="Query Vector", slot="left_bottom"),
                StudyVisualObject(id="candidates", kind="point_cloud", label="Semantic Matches", slot="center"),
                StudyVisualObject(id="match", kind="document", label="Nearest Chunk", slot="right_mid"),
            ]
            beats = [
                StudyVisualBeat(cue="query", action="reveal", target="query"),
                StudyVisualBeat(cue="vector", action="transform", target="qvec", source="query", weight=2),
                StudyVisualBeat(cue="similarity", action="scan", target="candidates", source="qvec", weight=3),
                StudyVisualBeat(cue="nearest", action="compare", target="candidates", source="qvec", destination="candidates", weight=2),
                StudyVisualBeat(cue="nearest", action="select", target="match", source="candidates", weight=2),
                StudyVisualBeat(cue="retrieve", action="move", target="match", source="candidates", destination="match", weight=2),
            ]
            return sb.model_copy(update={
                "purpose": "Compare similarity scores and visibly select the nearest chunk.",
                "layout": "split", "objects": objects, "beats": beats,
                "teaching_pattern": "retrieval_match",
                "reference_keywords": ["query vector similarity nearest chunk"],
                "environment": "data_space",
                "camera_style": "follow",
                "motion_density": "high",
            })



        return sb

    @classmethod
    def _repair_semantic_requirements(
        cls, sb: StudySceneStoryboard, narration: str, topic: str
    ) -> StudySceneStoryboard:
        """Repair recoverable semantic defects before the quality gate.

        The gate remains strict, but known failure modes are repaired into a
        semantically valid teaching scene instead of terminating the workflow.
        """
        lower = narration.lower()
        kinds = {obj.kind for obj in sb.objects}
        actions = {beat.action for beat in sb.beats}

        if sb.layout == "analogy_map":
            already_semantic = (
                bool(kinds & {"person", "place", "file", "folder", "document", "user"})
                and bool(kinds & {"host", "client", "server", "agent", "model", "tool", "resource"})
                and bool(actions & {"transform", "replace"})
            )
            if already_semantic:
                return sb

            restaurant_markers = {"restaurant", "kitchen", "waiter", "customer", "chef", "pantry"}
            if len(restaurant_markers & set(re.findall(r"[a-z]+", lower))) >= 2:
                objects = [
                    StudyVisualObject(id="customer", kind="person", label="Customer", slot="left_top"),
                    StudyVisualObject(id="waiter", kind="person", label="Waiter", slot="left_mid"),
                    StudyVisualObject(id="kitchen", kind="place", label="Kitchen / Pantry", slot="left_bottom"),
                    StudyVisualObject(id="host", kind="host", label="Host", slot="right_top"),
                    StudyVisualObject(id="client", kind="client", label="MCP Client", slot="right_mid"),
                    StudyVisualObject(id="server", kind="server", label="MCP Server", slot="right_bottom"),
                ]
                beats = [
                    StudyVisualBeat(cue="restaurant analogy", action="reveal", target="customer"),
                    StudyVisualBeat(cue="waiter", action="reveal", target="waiter"),
                    StudyVisualBeat(cue="kitchen", action="reveal", target="kitchen"),
                    StudyVisualBeat(cue="host", action="transform", target="host", source="customer", weight=2),
                    StudyVisualBeat(cue="client", action="transform", target="client", source="waiter", weight=2),
                    StudyVisualBeat(cue="server", action="transform", target="server", source="kitchen", weight=2),
                    StudyVisualBeat(cue="standard protocol", action="connect", target="server", source="client", destination="server"),
                ]
                return sb.model_copy(
                    update={
                        "purpose": "Transform the restaurant mental model into the concrete MCP host/client/server architecture.",
                        "objects": objects,
                        "beats": beats,
                        "reference_keywords": ["restaurant waiter kitchen", "MCP host client server"],
                    }
                )
            return sb

        if sb.layout == "code_plus_state":
            if "code" in kinds and bool(actions & {"type_code", "step_code"}):
                return sb
            nouns = cls._noun_phrases(narration)
            state_label = nouns[0] if nouns else "Runtime State"
            result_label = nouns[1] if len(nouns) > 1 else "Observed Result"
            is_rag = cls._is_rag_text(f"{topic} {narration}")
            code_label = "RAG Pipeline" if is_rag else "Execution Steps"
            code_detail = (
                [
                    "docs = retrieve(query)",
                    "context = join(docs)",
                    "answer = generate(query, context)",
                    "verify(answer, docs)",
                ]
                if is_rag
                else [
                    "state = read_input()",
                    "decision = evaluate(state)",
                    "result = execute(decision)",
                    "state = observe(result)",
                ]
            )
            objects = [
                StudyVisualObject(
                    id="code",
                    kind="code",
                    label=code_label,
                    slot="left_mid",
                    detail=code_detail,
                ),
                StudyVisualObject(id="state", kind="terminal", label=state_label[:64], slot="right_top"),
                StudyVisualObject(id="result", kind="resource", label=result_label[:64], slot="right_bottom"),
            ]
            beats = [
                StudyVisualBeat(cue="code begins", action="type_code", target="code"),
                StudyVisualBeat(cue="first execution step", action="step_code", target="code", weight=2),
                StudyVisualBeat(cue="state changes", action="reveal", target="state"),
                StudyVisualBeat(cue="next execution step", action="step_code", target="code", weight=2),
                StudyVisualBeat(cue="result appears", action="reveal", target="result"),
            ]
            return sb.model_copy(update={"objects": objects, "beats": beats})

        if sb.layout == "boundary":
            if bool(kinds & {"gate", "shield", "lock"}) and bool(actions & {"allow", "reject"}):
                return sb
            if any(term in lower for term in ("path traversal", "file path", "directory", "sandbox")):
                incoming, allowed, blocked = "Requested Path", "Allowed Directory", "Blocked Traversal"
            elif any(term in lower for term in ("prompt injection", "unauthorized", "permission", "security")):
                incoming, allowed, blocked = "External Input", "Authorized Action", "Unauthorized Action"
            else:
                incoming, allowed, blocked = "Incoming Request", "Allowed Input", "Rejected Input"
            objects = [
                StudyVisualObject(id="request", kind="packet", label=incoming, slot="left_mid"),
                StudyVisualObject(id="gate", kind="gate", label="Validation Boundary", slot="center"),
                StudyVisualObject(id="allowed", kind="resource", label=allowed, slot="right_top"),
                StudyVisualObject(id="blocked", kind="shield", label=blocked, slot="right_bottom"),
            ]
            beats = [
                StudyVisualBeat(cue="request arrives", action="reveal", target="request"),
                StudyVisualBeat(cue="validation boundary", action="reveal", target="gate"),
                StudyVisualBeat(cue="invalid input", action="reject", target="gate", source="request", destination="blocked", label="BLOCK", weight=2),
                StudyVisualBeat(cue="valid input", action="allow", target="gate", source="request", destination="allowed", label="ALLOW", weight=2),
                StudyVisualBeat(cue="protected result", action="highlight", target="allowed"),
            ]
            return sb.model_copy(update={"objects": objects, "beats": beats})

        # A packet without movement is decorative. Add explicit state travel so
        # request/response/data-flow scenes always teach where information goes.
        if "packet" in kinds and sb.layout in {"left_to_right", "split", "freeform"} and not bool(actions & {"send", "return", "move"}):
            packet = next(obj for obj in sb.objects if obj.kind == "packet")
            endpoints = [
                obj for obj in sb.objects
                if obj.id != packet.id and obj.kind in {"user", "model", "agent", "host", "client", "server", "tool", "resource", "database", "api", "file", "document", "graph", "chart", "number_line", "quantity", "vector", "experiment"}
            ]
            if len(endpoints) < 2:
                endpoints = [obj for obj in sb.objects if obj.id != packet.id]
            if len(endpoints) >= 2:
                source, destination = endpoints[0], endpoints[1]
                beats = list(sb.beats)
                if len(beats) >= 12:
                    beats = beats[:-1]
                beats.append(
                    StudyVisualBeat(
                        cue="information moves",
                        action="send",
                        target=packet.id,
                        source=source.id,
                        destination=destination.id,
                        weight=2,
                    )
                )
                return sb.model_copy(update={"beats": beats})

        # Definition/overview scenes can legitimately be simple, but they still
        # need a learner-visible state change. Prefer a semantic selection over
        # decorative pulses so the active concept clearly becomes the focus.
        state_actions = {
            "move", "send", "return", "transform", "replace", "split", "merge",
            "scan", "stream", "step_code", "allow", "reject", "select", "compare",
        }
        if not (actions & state_actions) and sb.objects:
            beats = list(sb.beats)
            focus_target = sb.objects[-1].id
            focus_beat = StudyVisualBeat(
                cue="key idea",
                action="select",
                target=focus_target,
                weight=1,
            )
            if len(beats) < 12:
                beats.append(focus_beat)
            else:
                beats[-1] = focus_beat
            return sb.model_copy(update={"beats": beats})

        return sb

    @staticmethod
    def _contains_terms(text: str, terms: tuple[str, ...] | list[str]) -> bool:
        """Match semantic terms as words/phrases, never accidental substrings."""
        haystack = re.sub(r"\s+", " ", str(text or "").lower())
        for term in terms:
            pattern = r"(?<![a-z0-9])" + re.escape(term.lower()).replace(r"\ ", r"\s+") + r"(?![a-z0-9])"
            if re.search(pattern, haystack):
                return True
        return False

    @staticmethod
    def _label_grounded_in_narration(label: str, narration: str) -> bool:
        stop = {"the", "a", "an", "and", "or", "to", "of", "for", "with", "system", "model", "technical"}
        label_tokens = [t for t in re.findall(r"[a-z0-9]+", label.lower()) if len(t) >= 3 and t not in stop]
        narration_tokens = set(re.findall(r"[a-z0-9]+", narration.lower()))
        return bool(label_tokens) and any(token in narration_tokens for token in label_tokens)

    @classmethod
    def _analogy_entities(cls, narration: str) -> list[tuple[str, str]]:
        """Extract only analogy nouns literally present in narration."""
        lower = narration.lower()
        catalog = [
            ("operating system", "device"), ("smartphone", "device"), ("phone", "device"),
            ("application", "app"), ("apps", "app"), ("app", "app"),
            ("hardware sensors", "sensor"), ("sensor", "sensor"), ("camera", "sensor"), ("gps", "sensor"),
            ("dining room", "place"), ("restaurant", "place"), ("kitchen", "place"), ("pantry", "place"),
            ("customer", "person"), ("waiter", "person"), ("assistant", "person"),
            ("library", "place"), ("librarian", "person"), ("book", "book"),
            ("mailbox", "place"), ("post office", "place"), ("letter", "document"),
            ("factory", "place"), ("worker", "person"), ("conveyor", "connector"),
        ]
        out: list[tuple[str, str]] = []
        for phrase, kind in catalog:
            if cls._contains_terms(lower, [phrase]):
                label = phrase.upper() if phrase == "gps" else phrase.title()
                if (label, kind) not in out:
                    out.append((label, kind))
        return out

    @classmethod
    def _repair_analogy_grounding(cls, sb: StudySceneStoryboard, narration: str) -> StudySceneStoryboard:
        if sb.layout != "analogy_map":
            return sb
        real_kinds = {"person", "place", "device", "app", "sensor", "file", "folder", "document", "book", "user"}
        candidates = cls._analogy_entities(narration)
        if not candidates:
            return sb
        used: set[str] = set()
        objects: list[StudyVisualObject] = []
        candidate_index = 0
        changed = False
        for obj in sb.objects:
            if obj.kind not in real_kinds or cls._label_grounded_in_narration(obj.label, narration):
                objects.append(obj)
                used.add(obj.label.lower())
                continue
            while candidate_index < len(candidates) and candidates[candidate_index][0].lower() in used:
                candidate_index += 1
            if candidate_index < len(candidates):
                label, kind = candidates[candidate_index]
                candidate_index += 1
                objects.append(obj.model_copy(update={"label": label, "kind": kind}))
                used.add(label.lower())
                changed = True
            else:
                objects.append(obj)
        if changed:
            print(f"[ANALOGY GROUNDING] scene={sb.scene_id} replaced invented analogy nouns with narration terms")
        return sb.model_copy(update={"objects": objects})

    @classmethod
    def _repair_temporal_alignment(
        cls,
        sb: StudySceneStoryboard,
        scene: object,
        topic: str,
    ) -> StudySceneStoryboard:
        """Prevent a scene from visually jumping ahead of its narration.

        This is intentionally conservative: it only blocks strongly specialized
        visual grammars when the spoken window contains no matching concept.
        """
        narration = str(getattr(scene, "description", ""))
        lower = narration.lower()
        kinds = {obj.kind for obj in sb.objects}
        actions = {beat.action for beat in sb.beats}

        security_terms = (
            "security", "secure", "safe", "permission", "authorize", "authorization",
            "validate", "validation", "invalid", "malicious", "attack", "sandbox",
            "boundary", "reject", "block", "untrusted", "injection", "protect",
            "verify", "verification", "grounded", "hallucination", "faithful",
            "evidence", "citation", "supported", "unsupported",
        )
        math_terms = (
            "algebra", "geometry", "calculus", "trigonometry", "equation", "formula",
            "fraction", "derivative", "integral", "slope", "angle", "theorem", "matrix",
            "polynomial", "probability", "statistics", "number line",
        )
        science_terms = (
            "physics", "chemistry", "biology", "atom", "molecule", "force", "velocity",
            "acceleration", "wave", "frequency", "experiment", "reaction", "energy",
        )
        browser_terms = ("browser", "web page", "website", "dom", "locator", "click", "ui")
        code_terms = (
            "code", "implement", "implementation", "function", "handler", "script",
            "python", "javascript", "typescript", "terminal", "command", "loop",
        )

        mismatch = False
        if (kinds & {"gate", "shield", "lock"} or actions & {"allow", "reject"}) and not cls._contains_terms(lower, security_terms):
            mismatch = True
        if kinds & {"equation", "number_line", "shape"} and not cls._contains_terms(lower, math_terms):
            mismatch = True
        if kinds & {"atom", "molecule", "wave", "experiment"} and not cls._contains_terms(lower, science_terms):
            mismatch = True
        if "browser" in kinds and not cls._contains_terms(lower, browser_terms):
            mismatch = True
        if (kinds & {"code", "terminal"}) and not cls._contains_terms(lower, code_terms):
            # JSON/protocol payloads may be shown as code only when the current
            # narration explicitly names JSON/schema/request/response structures.
            if not cls._contains_terms(lower, ("json", "schema", "payload", "request", "response")):
                mismatch = True

        if not mismatch:
            return sb

        replacement = cls._neutral_current_scene_storyboard(topic, scene)
        print(
            f"[TEMPORAL ALIGNMENT REPAIR] scene={int(getattr(scene, 'id'))} "
            "removed visuals not yet supported by current narration"
        )
        return replacement

    @classmethod
    def _neutral_current_scene_storyboard(
        cls,
        topic: str,
        scene: object,
    ) -> StudySceneStoryboard:
        narration = str(getattr(scene, "description", ""))
        lower = narration.lower()
        scene_id = int(getattr(scene, "id"))
        labels = cls._noun_phrases(narration)[:6]

        def has(*terms: str) -> bool:
            return cls._contains_terms(lower, list(terms))

        objects: list[StudyVisualObject]
        beats: list[StudyVisualBeat]
        layout = "left_to_right"

        if has("mcp", "protocol", "client", "server", "connector", "integration", "data source", "external data", "api"):
            left_label = "AI Model" if has("model", "llm", "language model") else (labels[0] if labels else "Learner Input")
            middle_label = "Standard Interface" if has("protocol", "standard", "integration", "connector") else "Connection"
            right_label = "External Data" if has("data", "file", "database", "resource") else "Capability"
            objects = [
                StudyVisualObject(id="source", kind="model", label=left_label[:64], slot="left_mid"),
                StudyVisualObject(id="bridge", kind="connector", label=middle_label[:64], slot="center"),
                StudyVisualObject(id="target", kind="resource", label=right_label[:64], slot="right_mid"),
            ]
            beats = [
                StudyVisualBeat(cue="problem appears", action="reveal", target="source"),
                StudyVisualBeat(cue="connection", action="reveal", target="bridge"),
                StudyVisualBeat(cue="external data", action="reveal", target="target"),
                StudyVisualBeat(cue="standard connection", action="connect", target="bridge", source="source", destination="target", weight=2),
            ]
        elif has("algebra", "geometry", "calculus", "equation", "formula", "fraction", "derivative", "integral", "probability", "statistics"):
            layout = "split"
            objects = [
                StudyVisualObject(id="relation", kind="equation", label=(labels[0] if labels else "Relationship")[:64], slot="left_mid"),
                StudyVisualObject(id="visual", kind="graph", label=(labels[1] if len(labels)>1 else "Visual Model")[:64], slot="right_mid"),
                StudyVisualObject(id="result", kind="quantity", label=(labels[2] if len(labels)>2 else "Result")[:64], slot="center_bottom"),
            ]
            beats = [
                StudyVisualBeat(cue="relationship", action="reveal", target="relation"),
                StudyVisualBeat(cue="visual model", action="reveal", target="visual"),
                StudyVisualBeat(cue="compare", action="compare", target="visual", source="relation", destination="visual", weight=2),
                StudyVisualBeat(cue="result", action="select", target="result", weight=2),
            ]
        elif has("physics", "chemistry", "biology", "atom", "molecule", "force", "wave", "experiment", "reaction"):
            layout = "split"
            objects = [
                StudyVisualObject(id="system", kind="experiment", label=(labels[0] if labels else "System")[:64], slot="left_mid"),
                StudyVisualObject(id="measure", kind="quantity", label=(labels[1] if len(labels)>1 else "Measurement")[:64], slot="center"),
                StudyVisualObject(id="result", kind="graph", label=(labels[2] if len(labels)>2 else "Observed Result")[:64], slot="right_mid"),
            ]
            beats = [
                StudyVisualBeat(cue="system", action="reveal", target="system"),
                StudyVisualBeat(cue="measurement", action="reveal", target="measure"),
                StudyVisualBeat(cue="observed result", action="compare", target="result", source="system", destination="result", weight=2),
                StudyVisualBeat(cue="result", action="select", target="result", weight=2),
            ]
        else:
            objects = [
                StudyVisualObject(id="idea", kind="text", label=(labels[0] if labels else topic)[:64], slot="left_mid"),
                StudyVisualObject(id="mechanism", kind="resource", label=(labels[1] if len(labels)>1 else "Mechanism")[:64], slot="center"),
                StudyVisualObject(id="outcome", kind="tool", label=(labels[2] if len(labels)>2 else "Outcome")[:64], slot="right_mid"),
            ]
            beats = [
                StudyVisualBeat(cue="current idea", action="reveal", target="idea"),
                StudyVisualBeat(cue="mechanism", action="reveal", target="mechanism"),
                StudyVisualBeat(cue="relationship", action="connect", target="mechanism", source="idea", destination="mechanism", weight=2),
                StudyVisualBeat(cue="outcome", action="select", target="outcome", weight=2),
            ]

        sb = StudySceneStoryboard(
            scene_id=scene_id,
            purpose="Visualize only the concepts spoken in the current narration window.",
            layout=layout,
            objects=objects,
            beats=beats,
            reference_keywords=[obj.label for obj in objects[:3]],
        )
        return cls._repair_cues(sb, narration)

    @staticmethod
    def _repair_cues(sb: StudySceneStoryboard, narration: str) -> StudySceneStoryboard:
        """Guarantee speech-aligned beat cues.

        LLMs occasionally return descriptive cue names instead of literal narration
        phrases. The renderer needs literal anchors, so invalid cues are replaced
        with evenly distributed verbatim word windows from the narration.
        """
        words = re.findall(r"\S+", narration or "")
        normalized_narration = re.sub(r"\s+", " ", narration.lower()).strip()
        beats: list[StudyVisualBeat] = []
        total = max(1, len(sb.beats))
        for index, beat in enumerate(sb.beats):
            cue_norm = re.sub(r"\s+", " ", beat.cue.lower()).strip()
            if cue_norm and cue_norm in normalized_narration:
                beats.append(beat)
                continue
            if not words:
                beats.append(beat.model_copy(update={"cue": beat.cue[:120] or "scene"}))
                continue
            anchor = round(index / max(1, total - 1) * max(0, len(words) - 5))
            window = words[anchor : anchor + min(6, len(words) - anchor)]
            cue = " ".join(window).strip() or " ".join(words[:4])
            beats.append(beat.model_copy(update={"cue": cue[:120]}))
        return sb.model_copy(update={"beats": beats})

    @staticmethod
    def _summary(sb: StudySceneStoryboard) -> str:
        kinds = ",".join(obj.kind for obj in sb.objects)
        actions = ",".join(beat.action for beat in sb.beats)
        return f"scene {sb.scene_id}: phase={sb.learning_phase}; {sb.layout}; kinds={kinds}; actions={actions}"

    @classmethod
    def _fallback(cls, topic: str, scene: object) -> StudySceneStoryboard:
        plan = StudySemanticPlanner.plan_scene(
            scene_id=int(getattr(scene, "id")),
            topic=topic,
            title=str(getattr(scene, "title", "")),
            description=str(getattr(scene, "description", "")),
            key_elements=[str(v) for v in getattr(scene, "key_elements", [])],
            visual_type=str(getattr(scene, "visual_type", "")),
        )
        labels = [x for x in plan.labels if cls._good_label(x, topic, str(getattr(scene, "title", "")))]
        labels = labels[:6] or cls._noun_phrases(str(getattr(scene, "description", "")))[:6]
        while len(labels) < 4:
            labels.append(["Input", "Process", "Result", "Verify"][len(labels)])

        subject_text = (
            f"{topic} {getattr(scene, 'title', '')} {getattr(scene, 'description', '')}".lower()
        )
        math_subject = cls._contains_terms(subject_text, (
            "math", "mathematics", "algebra", "geometry", "calculus", "trigonometry", "probability",
            "statistics", "equation", "formula", "fraction", "derivative", "integral",
            "slope", "angle", "theorem", "matrix", "polynomial",
        ))
        science_subject = cls._contains_terms(subject_text, (
            "physics", "chemistry", "biology", "science", "atom", "molecule",
            "force", "velocity", "acceleration", "wave", "frequency", "experiment",
            "cell", "reaction", "energy",
        ))

        kind_map = {
            "architecture_network": ["client", "server", "resource", "packet"],
            "message_exchange": ["client", "server", "packet", "packet"],
            "many_to_one": ["client", "client", "server", "connector"],
            "capability_orbit": ["server", "tool", "resource", "prompt"],
            "validation_gate": ["packet", "gate", "badge", "badge"],
            "security_boundary": ["client", "shield", "resource", "gate"],
            "tradeoff_balance": ["balance", "resource", "shield", "badge"],
            "retrieval_pipeline": ["document", "vector_store", "resource", "model"],
            "request_response": ["client", "server", "packet", "packet"],
            "browser_action": ["browser", "node", "badge", "user"],
            "browser_test": ["browser", "node", "badge", "badge"],
            "query_table": ["database", "table", "packet", "badge"],
            "algorithm_trace": ["array", "badge", "badge", "badge"],
            "agent_tool_loop": ["agent", "tool", "resource", "badge"],
            "analogy_transform": ["person", "place", "client", "server"],
            "code_execution": ["code", "terminal", "badge", "resource"],
            "concept_map": ["resource", "tool", "client", "server"],
            "build_challenge": ["tool", "code", "badge", "badge"],
            "concept_reveal": ["text", "resource", "tool", "server"],
        }
        layout_map = {
            "architecture_network": "left_to_right", "message_exchange": "left_to_right",
            "many_to_one": "left_to_right", "capability_orbit": "radial",
            "validation_gate": "boundary", "security_boundary": "boundary",
            "tradeoff_balance": "split", "retrieval_pipeline": "left_to_right",
            "request_response": "left_to_right", "browser_action": "browser_demo",
            "browser_test": "browser_demo", "query_table": "table_focus",
            "algorithm_trace": "array_trace", "agent_tool_loop": "radial",
            "analogy_transform": "analogy_map", "timeline_build": "timeline",
            "code_execution": "code_plus_state", "concept_map": "freeform",
            "build_challenge": "stack", "concept_reveal": "freeform",
        }
        slots = ["left_mid", "center", "right_mid", "center_bottom", "right_bottom", "left_bottom"]
        kinds = kind_map.get(plan.archetype, ["node"] * 4)
        fallback_layout = layout_map.get(plan.archetype, "freeform")
        if math_subject:
            kinds = ["equation", "graph", "quantity", "number_line"]
            fallback_layout = "split"
        elif science_subject:
            if "atom" in subject_text or "molecule" in subject_text or "chemistry" in subject_text:
                kinds = ["molecule", "atom", "quantity", "chart"]
            elif "wave" in subject_text or "frequency" in subject_text:
                kinds = ["wave", "graph", "quantity", "vector"]
            else:
                kinds = ["experiment", "quantity", "graph", "vector"]
            fallback_layout = "split"
        description = str(getattr(scene, "description", ""))
        objects: list[StudyVisualObject] = []
        for i, label in enumerate(labels[:6]):
            kind = kinds[i % len(kinds)]
            detail: list[str] = []
            if kind == "code":
                # Fallback code is intentionally structural rather than a made-up product API.
                detail = ["request = parse(message)", "validate(request)", "result = execute(request)", "return result"]
            objects.append(
                StudyVisualObject(
                    id=f"o{i+1}",
                    kind=kind,
                    label=label,
                    slot=slots[i % len(slots)],
                    detail=detail,
                )
            )

        if math_subject:
            actions = [
                StudyVisualBeat(cue="relationship", action="reveal", target="o1"),
                StudyVisualBeat(cue="visual representation", action="reveal", target="o2"),
                StudyVisualBeat(cue="compare values", action="compare", target="o2", source="o1", destination="o2", weight=2),
                StudyVisualBeat(cue="known value", action="reveal", target="o3"),
                StudyVisualBeat(cue="result", action="select", target="o3", weight=2),
            ]
        elif science_subject:
            actions = [
                StudyVisualBeat(cue="system", action="reveal", target="o1"),
                StudyVisualBeat(cue="measurement", action="reveal", target="o2"),
                StudyVisualBeat(cue="observed relationship", action="compare", target="o2", source="o1", destination="o2", weight=2),
                StudyVisualBeat(cue="result", action="reveal", target="o3"),
                StudyVisualBeat(cue="evidence", action="select", target="o3", weight=2),
            ]
        elif plan.archetype == "analogy_transform":
            actions = [
                StudyVisualBeat(cue="analogy start", action="reveal", target="o1"),
                StudyVisualBeat(cue="analogy place", action="reveal", target="o2"),
                StudyVisualBeat(cue="technical mapping one", action="transform", target="o3", source="o1"),
                StudyVisualBeat(cue="technical mapping two", action="transform", target="o4", source="o2"),
                StudyVisualBeat(cue="mapping result", action="connect", target="o4", source="o3", destination="o4", weight=2),
            ]
        elif plan.archetype == "code_execution":
            actions = [
                StudyVisualBeat(cue="code starts", action="type_code", target="o1"),
                StudyVisualBeat(cue="code step one", action="step_code", target="o1", weight=2),
                StudyVisualBeat(cue="code step two", action="step_code", target="o1", weight=2),
                StudyVisualBeat(cue="execution output", action="reveal", target="o2"),
                StudyVisualBeat(cue="verify output", action="highlight", target="o2"),
            ]
        elif plan.archetype in {"validation_gate", "security_boundary"}:
            gate_target = "o2" if plan.archetype == "validation_gate" else "o4"
            actions = [
                StudyVisualBeat(cue="request arrives", action="reveal", target="o1"),
                StudyVisualBeat(cue="boundary appears", action="reveal", target=gate_target),
                StudyVisualBeat(cue="invalid path", action="reject", target=gate_target, label="BLOCK", weight=2),
                StudyVisualBeat(cue="valid path", action="allow", target=gate_target, label="ALLOW", weight=2),
                StudyVisualBeat(cue="protected result", action="highlight", target=gate_target),
            ]
        else:
            actions = [
                StudyVisualBeat(cue="first idea", action="reveal", target="o1", weight=1),
                StudyVisualBeat(cue="next mechanism", action="reveal", target="o2", weight=1),
                StudyVisualBeat(cue="relationship", action="connect", target="o2", source="o1", destination="o2", weight=2),
                StudyVisualBeat(cue="advance mechanism", action="reveal", target="o3", weight=1),
                StudyVisualBeat(cue="information moves", action="send", target="o3", source="o2", destination="o3", weight=2),
                StudyVisualBeat(cue="resulting state", action="reveal", target="o4", weight=1),
                StudyVisualBeat(cue="takeaway", action="highlight", target="o4", weight=1),
            ]
        return StudySceneStoryboard(
            scene_id=int(getattr(scene, "id")),
            purpose=f"Explain {str(getattr(scene, 'title', topic))} through changing state, not a static diagram.",
            layout=fallback_layout,
            objects=objects,
            beats=actions,
            reference_keywords=labels[:4],
        )

    @staticmethod
    def _good_label(value: str, topic: str, title: str) -> bool:
        v = re.sub(r"\s+", " ", value).strip().lower()
        if not v or v in {
            topic.lower(), title.lower(), "context", "core idea", "mechanism", "takeaway",
            "for example", "for instance", "in practice", "in other words", "next", "then",
            "first", "finally", "however", "therefore",
        }:
            return False
        return len(v.split()) <= 6 and len(v) <= 56

    @staticmethod
    def _noun_phrases(text: str) -> list[str]:
        terms = re.findall(r"\b(?:[A-Z][A-Za-z0-9+.#-]*|[a-z][a-z0-9+.#-]{3,})(?:\s+(?:[A-Z][A-Za-z0-9+.#-]*|[a-z][a-z0-9+.#-]{3,})){0,2}\b", text)
        stop = {"this", "that", "with", "from", "have", "will", "into", "when", "then", "your", "what", "which"}
        out: list[str] = []
        for term in terms:
            words = term.lower().split()
            if all(w in stop for w in words):
                continue
            if term.lower() not in {x.lower() for x in out}:
                out.append(term)
        return out

    @staticmethod
    def _repair_cross_scene_repetition(items: list[StudySceneStoryboard]) -> list[StudySceneStoryboard]:
        """Prevent near-clone adjacent scenes, not only byte-identical signatures."""
        if not items:
            return items
        repaired = [items[0]]
        alternate_layout = {
            "left_to_right": "split", "freeform": "stack", "stack": "split",
            "split": "freeform", "radial": "freeform", "boundary": "split",
            "code_plus_state": "code_plus_state", "timeline": "left_to_right", "analogy_map": "analogy_map",
            "browser_demo": "browser_demo", "table_focus": "table_focus", "array_trace": "array_trace",
        }
        layout_streak = 1
        for current in items[1:]:
            prev = repaired[-1]
            same_layout = current.layout == prev.layout
            layout_streak = layout_streak + 1 if same_layout else 1
            prev_kinds = {o.kind for o in prev.objects}
            cur_kinds = {o.kind for o in current.objects}
            prev_actions = {b.action for b in prev.beats}
            cur_actions = {b.action for b in current.beats}
            kind_sim = len(prev_kinds & cur_kinds) / max(1, len(prev_kinds | cur_kinds))
            action_sim = len(prev_actions & cur_actions) / max(1, len(prev_actions | cur_actions))
            near_clone = current.signature == prev.signature or (same_layout and kind_sim >= 0.72 and action_sim >= 0.72)
            if near_clone or layout_streak >= 3:
                alt = alternate_layout.get(current.layout, "freeform")
                if alt != current.layout:
                    current = current.model_copy(update={"layout": alt})
                    layout_streak = 1
            repaired.append(current)
        return repaired

