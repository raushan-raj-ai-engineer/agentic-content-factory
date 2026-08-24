from pathlib import Path

from content_factory.agents.base import Agent
from content_factory.models.content import (
    VisualArtifact,
    VisualGenerationResult,
)
from content_factory.orchestration.state import WorkflowState
from content_factory.utils.artifact_paths import artifact_subdir
from content_factory.visual.base import VisualProvider


class VisualGenerationAgent(Agent):
    """Generate one local visual for each production scene."""

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
            )

        for scene in state.production_plan.visual_scenes:
            output_path = (
                output_dir
                / f"scene_{scene.id}.png"
            )

            prompt = (
                f"Subject: {scene.subject}. "
                f"Description: {scene.description}. "
                f"Key elements: {', '.join(scene.key_elements)}. "
                f"Composition: {scene.composition}. "
                f"Style: {scene.style}. "
                f"Avoid: {', '.join(scene.avoid)}."
            )

            await self._visual_provider.generate(
                prompt=prompt,
                output_path=str(output_path),
                title=scene.title,
                description=scene.description,
                visual_type=scene.visual_type,
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
