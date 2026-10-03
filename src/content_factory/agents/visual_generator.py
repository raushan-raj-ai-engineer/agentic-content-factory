import json
from pathlib import Path

from content_factory.agents.base import Agent
from content_factory.modes import is_study_mode
from content_factory.models.content import (
    VisualArtifact,
    VisualGenerationResult,
)
from content_factory.orchestration.state import WorkflowState
from content_factory.utils.artifact_paths import artifact_subdir
from content_factory.visual.base import VisualProvider
from content_factory.visual.study_semantics import StudySemanticPlanner
from content_factory.visual.study_storyboard import StudySceneStoryboard


class VisualGenerationAgent(Agent):
    """Generate one local visual for each production scene."""

    _CINEMATIC_HINTS = {
        "hook", "opening", "intro", "introduction", "overview", "context",
        "what is", "why it matters", "big picture", "mental model", "what it means",
        "recap", "summary", "watch next",
    }

    def __init__(
        self,
        visual_provider: VisualProvider,
        output_root: str = "artifacts",
    ) -> None:
        self._visual_provider = visual_provider
        self._output_root = Path(output_root)

    @property
    def name(self) -> str:
        return "Visual Generation Agent"

    async def execute(
        self,
        state: WorkflowState,
    ) -> WorkflowState:
        if state.production_plan is None:
            raise ValueError(
                "Content production plan is required."
            )

        if not state.production_approved:
            raise ValueError(
                "Production plan must be approved before visual generation."
            )

        output_dir = artifact_subdir(
            state,
            "visuals",
            self._output_root,
        )

        artifacts: list[VisualArtifact] = []
        study_storyboards: dict[int, StudySceneStoryboard] = {}
        study_plans = {}
        if is_study_mode(state):
            storyboard_file = str(state.metadata.get("study_storyboard_file", "") or "")
            if storyboard_file and Path(storyboard_file).is_file():
                payload = json.loads(Path(storyboard_file).read_text(encoding="utf-8"))
                for item in payload.get("scenes", []):
                    sb = StudySceneStoryboard.model_validate(item)
                    study_storyboards[sb.scene_id] = sb
                expected = {scene.id for scene in state.production_plan.visual_scenes}
                if set(study_storyboards) != expected:
                    raise RuntimeError("Study storyboard IDs do not match production scene IDs")
                print(
                    "[STUDY PREFLIGHT] narration-driven storyboards validated: "
                    f"{len(study_storyboards)} scenes"
                )
            else:
                study_plans = StudySemanticPlanner.plan_all(
                    topic=(state.topic or state.production_plan.title),
                    scenes=state.production_plan.visual_scenes,
                )
                unsupported = {
                    plan.archetype
                    for plan in study_plans.values()
                    if plan.archetype not in StudySemanticPlanner.SUPPORTED_ARCHETYPES
                }
                if unsupported:
                    raise RuntimeError(
                        "Study semantic planner emitted unsupported Manim archetype(s): "
                        + ", ".join(sorted(unsupported))
                    )
                print(
                    "[STUDY PREFLIGHT] fallback semantic plans validated: "
                    f"{len(study_plans)} scenes"
                )

        set_context = getattr(
            self._visual_provider,
            "set_context",
            None,
        )
        if callable(set_context):
            set_context(
                topic=(
                    state.topic
                    or state.production_plan.title
                ),
                domain=str(
                    state.metadata.get(
                        "production_domain",
                        "",
                    )
                    or ""
                ),
                study_mode=is_study_mode(state),
            )

        for scene in state.production_plan.visual_scenes:
            output_path = (
                output_dir
                / f"scene_{scene.id}.png"
            )

            storyboard = study_storyboards.get(scene.id)
            reference_keywords = [] if storyboard is None else storyboard.reference_keywords
            reference_purpose = "" if storyboard is None else storyboard.purpose
            prompt = (
                f"Subject: {scene.subject}. "
                f"Description: {scene.description}. "
                f"Key elements: {', '.join(scene.key_elements)}. "
                f"Reference purpose: {reference_purpose}. "
                f"Reference keywords: {', '.join(reference_keywords)}. "
                f"Composition: {scene.composition}. "
                f"Style: {scene.style}. "
                "For study mode create scene-specific reference art, not a reusable flowchart template. "
                f"Avoid: {', '.join(scene.avoid)}."
            )

            reference_description = scene.description
            if storyboard is not None:
                object_labels = ", ".join(obj.label for obj in storyboard.objects[:8])
                reference_description = (
                    f"{storyboard.purpose}. Concrete visual subjects: {object_labels}. "
                    f"Narration: {scene.description}"
                )

            await self._visual_provider.generate(
                prompt=prompt,
                output_path=str(output_path),
                title=scene.title,
                description=reference_description,
                visual_type=scene.visual_type,
            )

            if is_study_mode(state):
                if storyboard is not None:
                    plan_path = output_path.with_suffix(output_path.suffix + ".storyboard.json")
                    payload = storyboard.model_dump()
                    payload["description"] = scene.description
                    payload["subject"] = scene.subject
                    payload["title"] = self._viewer_title(scene.title)
                    payload["reference_png"] = str(output_path)
                    payload["reference_style"] = self._study_reference_style(scene.title, scene.description, scene.id)
                    plan_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                    self._write_study_motion_policy(
                        output_path=output_path,
                        visual_type=scene.visual_type,
                        study_manifest=plan_path,
                        mode="study_storyboard_manim",
                        policy="study-animation-v9-theory-first",
                    )
                    print(
                        "[STUDY DIRECTOR] "
                        f"scene={scene.id} layout={storyboard.layout} "
                        f"objects={len(storyboard.objects)} beats={len(storyboard.beats)}"
                    )
                else:
                    plan = study_plans[scene.id]
                    plan_path = output_path.with_suffix(output_path.suffix + ".study.json")
                    plan_payload = plan.to_dict()
                    plan_payload["description"] = scene.description
                    plan_payload["key_elements"] = list(scene.key_elements)
                    plan_payload["subject"] = scene.subject
                    plan_payload["title"] = self._viewer_title(scene.title)
                    plan_payload["reference_png"] = str(output_path)
                    plan_payload["reference_style"] = self._study_reference_style(scene.title, scene.description, scene.id)
                    plan_path.write_text(json.dumps(plan_payload, indent=2), encoding="utf-8")
                    self._write_study_motion_policy(
                        output_path=output_path,
                        visual_type=scene.visual_type,
                        study_manifest=plan_path,
                    )

            if not output_path.is_file():
                raise RuntimeError(
                    f"Visual was not created: {output_path}"
                )

            artifacts.append(
                VisualArtifact(
                    scene_id=scene.id,
                    file_path=str(output_path),
                    provider="local",
                    status="generated",
                    visual_type=scene.visual_type,
                )
            )

        state.visual_generation = VisualGenerationResult(
            artifacts=artifacts
        )
        state.status = "visuals_generated"

        print(f"[ARTIFACT] Visuals: {output_dir}")

        release = getattr(
            self._visual_provider,
            "release",
            None,
        )
        if callable(release):
            released = release()
            if hasattr(
                released,
                "__await__",
            ):
                await released

        return state

    @classmethod
    def _write_study_motion_policy(
        cls,
        *,
        output_path: Path,
        visual_type: str,
        study_manifest: Path,
        mode: str = "study_semantic_manim",
        policy: str = "study-animation-v3-semantic-manim",
    ) -> None:
        sidecar = output_path.with_suffix(output_path.suffix + ".motion.json")
        sidecar.write_text(
            json.dumps(
                {
                    "mode": mode,
                    "required": True,
                    "policy": policy,
                    "scene_engine_version": "study-scene-engine-v7",
                    "renderer": "manim",
                    "study_manifest": study_manifest.name,
                    "visual_type": visual_type,
                    "whole_frame_zoom": False,
                    "static_png_primary": False,
                },
                indent=2,
            ),
            encoding="utf-8",
        )



    @staticmethod
    def _viewer_title(title: str) -> str:
        import re

        value = re.sub(r"\s+[—-]\s*\d+\.?$", "", str(title or "").strip())
        if value.lower() in {"context", "introduction", "intro"}:
            return ""
        words = value.split()
        if len(words) > 8:
            value = " ".join(words[:8])
        return value

    @classmethod
    def _study_reference_style(cls, title: str, description: str, scene_id: int) -> str:
        # v0.6.1: Study reference PNGs are decorative backdrops only. All
        # readable teaching text is rendered deterministically by Manim.
        return "hero_ambient" if scene_id == 1 else "vector_ambient"
