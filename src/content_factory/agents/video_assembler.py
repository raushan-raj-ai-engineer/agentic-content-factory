import json
from pathlib import Path

from content_factory.modes import is_study_mode
from content_factory.video.lesson import write_lesson

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
        *,
        output_dir: str | None = None,
    ) -> None:
        self._video_assembler = video_assembler
        self._output_root = Path(output_root)
        self._explicit_output_dir = Path(output_dir) if output_dir is not None else None

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

        if not voice_artifacts or len(voice_artifacts) != len(visual_artifacts):
            raise ValueError("Voice and visual counts must match and be non-empty")
        voice_ids = [a.segment_id for a in voice_artifacts]
        visual_ids = [a.scene_id for a in visual_artifacts]
        if len(set(voice_ids)) != len(voice_ids):
            raise ValueError("Duplicate voice segment IDs")
        if len(set(visual_ids)) != len(visual_ids):
            raise ValueError("Duplicate visual scene IDs")
        if voice_ids != visual_ids:
            raise ValueError("Voice and visual IDs must match")

        voice_files = [
            item.file_path
            for item in voice_artifacts
        ]
        visual_files = [
            item.file_path
            for item in visual_artifacts
        ]

        output_dir = self._explicit_output_dir or artifact_subdir(
            state,
            "video",
            self._output_root,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
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
        if is_study_mode(state) and state.production_plan is not None:
            board_path = Path(str(state.metadata.get("study_storyboard_file") or ""))
            boards = json.loads(board_path.read_text()).get("scenes", []) if board_path.is_file() else []
            lesson_path = output_dir / "lesson.html"
            write_lesson(
                lesson_path, voice_files,
                sorted(state.production_plan.visual_scenes, key=lambda scene: scene.id),
                boards, state.production_plan.title,
            )
            state.metadata["interactive_lesson_file"] = str(lesson_path)
        state.status = "video_assembled"

        print(f"[ARTIFACT] Video: {output_path}")

        return state
