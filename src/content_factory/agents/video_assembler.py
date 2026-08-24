from pathlib import Path

from content_factory.agents.base import Agent
from content_factory.models.content import (
    VideoArtifact,
    VideoAssemblyResult,
)
from content_factory.orchestration.state import WorkflowState
from content_factory.utils.artifact_paths import artifact_subdir
from content_factory.video.base import VideoAssembler


class VideoAssemblyAgent(Agent):
    """Assemble narration and visuals into the current topic/run folder."""

    def __init__(
        self,
        video_assembler: VideoAssembler,
        output_root: str = "artifacts",
    ) -> None:
        self._video_assembler = video_assembler
        self._output_root = Path(output_root)

    @property
    def name(self) -> str:
        return "Video Assembly Agent"

    async def execute(
        self,
        state: WorkflowState,
    ) -> WorkflowState:
        if state.voice_generation is None:
            raise ValueError(
                "Voice generation result is required."
            )

        if state.visual_generation is None:
            raise ValueError(
                "Visual generation result is required."
            )

        voice_artifacts = sorted(
            state.voice_generation.artifacts,
            key=lambda item: item.segment_id,
        )
        visual_artifacts = sorted(
            state.visual_generation.artifacts,
            key=lambda item: item.scene_id,
        )

        voice_files = [
            item.file_path
            for item in voice_artifacts
        ]
        visual_files = [
            item.file_path
            for item in visual_artifacts
        ]

        output_dir = artifact_subdir(
            state,
            "video",
            self._output_root,
        )
        output_path = (
            output_dir / "final_video.mp4"
        )

        duration = await self._video_assembler.assemble(
            voice_files=voice_files,
            visual_files=visual_files,
            output_path=str(output_path),
        )

        state.video_assembly = VideoAssemblyResult(
            artifact=VideoArtifact(
                file_path=str(output_path),
                duration_seconds=duration,
                voice_artifact_count=len(voice_files),
                visual_artifact_count=len(visual_files),
                provider="local",
                status="assembled",
            )
        )
        state.status = "video_assembled"

        print(f"[ARTIFACT] Video: {output_path}")

        return state
