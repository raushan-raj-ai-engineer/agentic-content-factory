from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from content_factory.agents.video_assembler import VideoAssemblyAgent
from content_factory.models.content import (
    VideoAssemblyResult,
    VisualArtifact,
    VisualGenerationResult,
    VoiceArtifact,
    VoiceGenerationResult,
)
from content_factory.orchestration.state import WorkflowState


def _voice_artifacts() -> list[VoiceArtifact]:
    return [
        VoiceArtifact(
            segment_id=2,
            file_path="audio/segment_2.wav",
            duration_seconds=20,
            provider="local",
            status="generated",
        ),
        VoiceArtifact(
            segment_id=1,
            file_path="audio/segment_1.wav",
            duration_seconds=10,
            provider="local",
            status="generated",
        ),
    ]


def _visual_artifacts() -> list[VisualArtifact]:
    return [
        VisualArtifact(
            scene_id=1,
            file_path="visuals/scene_1.png",
            visual_type="talking_head",
            provider="local",
            status="generated",
        ),
        VisualArtifact(
            scene_id=2,
            file_path="visuals/scene_2.png",
            visual_type="architecture_diagram",
            provider="local",
            status="generated",
        ),
    ]


def _state() -> WorkflowState:
    state = WorkflowState(
        run_id="test-run",
    )

    state.voice_generation = VoiceGenerationResult(
        artifacts=_voice_artifacts(),
    )

    state.visual_generation = VisualGenerationResult(
        artifacts=_visual_artifacts(),
    )

    return state


@pytest.mark.asyncio
async def test_video_assembly_orders_artifacts_by_id(
    tmp_path: Path,
) -> None:
    assembler = AsyncMock()
    assembler.assemble.return_value = 30

    agent = VideoAssemblyAgent(
        video_assembler=assembler,
        output_dir=str(tmp_path),
    )

    state = _state()

    result = await agent.execute(state)

    assembler.assemble.assert_awaited_once_with(
        voice_files=[
            "audio/segment_1.wav",
            "audio/segment_2.wav",
        ],
        visual_files=[
            "visuals/scene_1.png",
            "visuals/scene_2.png",
        ],
        output_path=str(tmp_path / "final_video.mp4"),
    )

    assert result.status == "video_assembled"
    assert result.video_assembly is not None
    assert isinstance(
        result.video_assembly,
        VideoAssemblyResult,
    )
    assert result.video_assembly.artifact.duration_seconds == 30


@pytest.mark.asyncio
async def test_video_assembly_rejects_count_mismatch(
    tmp_path: Path,
) -> None:
    assembler = AsyncMock()

    agent = VideoAssemblyAgent(
        video_assembler=assembler,
        output_dir=str(tmp_path),
    )

    state = _state()

    state.visual_generation = VisualGenerationResult(
        artifacts=_visual_artifacts()[:1],
    )

    with pytest.raises(
        ValueError,
        match="counts must match",
    ):
        await agent.execute(state)

    assembler.assemble.assert_not_awaited()


@pytest.mark.asyncio
async def test_video_assembly_rejects_duplicate_voice_ids(
    tmp_path: Path,
) -> None:
    assembler = AsyncMock()

    agent = VideoAssemblyAgent(
        video_assembler=assembler,
        output_dir=str(tmp_path),
    )

    state = _state()

    state.voice_generation = VoiceGenerationResult(
        artifacts=[
            VoiceArtifact(
                segment_id=1,
                file_path="audio/segment_1.wav",
                duration_seconds=10,
                provider="local",
                status="generated",
            ),
            VoiceArtifact(
                segment_id=1,
                file_path="audio/segment_1_retry.wav",
                duration_seconds=10,
                provider="local",
                status="generated",
            ),
        ],
    )

    with pytest.raises(
        ValueError,
        match="Duplicate voice segment IDs",
    ):
        await agent.execute(state)

    assembler.assemble.assert_not_awaited()


@pytest.mark.asyncio
async def test_video_assembly_rejects_id_mismatch(
    tmp_path: Path,
) -> None:
    assembler = AsyncMock()

    agent = VideoAssemblyAgent(
        video_assembler=assembler,
        output_dir=str(tmp_path),
    )

    state = _state()

    state.visual_generation = VisualGenerationResult(
        artifacts=[
            VisualArtifact(
                scene_id=1,
                file_path="visuals/scene_1.png",
                visual_type="talking_head",
                provider="local",
                status="generated",
            ),
            VisualArtifact(
                scene_id=3,
                file_path="visuals/scene_3.png",
                visual_type="workflow",
                provider="local",
                status="generated",
            ),
        ],
    )

    with pytest.raises(
        ValueError,
        match="IDs must match",
    ):
        await agent.execute(state)

    assembler.assemble.assert_not_awaited()


def test_storyboard_portable_manim_repair_stays_animated_and_removes_sensitive_kinds():
    from content_factory.video.local import LocalVideoAssembler

    spec = {
        "objects": [
            {"id": "code", "kind": "code", "label": "Tool implementation", "slot": "wide_mid", "detail": ["result = tool()"]},
            {"id": "term", "kind": "terminal", "label": "result", "slot": "right_bottom", "detail": []},
            {"id": "server", "kind": "server", "label": "MCP Server", "slot": "left_mid", "detail": []},
        ],
        "beats": [
            {"cue": "show", "action": "type_code", "target": "code", "weight": 1},
            {"cue": "step", "action": "step_code", "target": "code", "weight": 1},
            {"cue": "connect", "action": "connect", "target": "server", "source": "server", "destination": "code", "weight": 1},
            {"cue": "result", "action": "reveal", "target": "term", "weight": 1},
        ],
    }

    repaired = LocalVideoAssembler._repair_storyboard_spec_for_manim(spec)
    assert repaired["render_repair"] == "portable-semantic-v3"
    assert [o["kind"] for o in repaired["objects"]] == ["node", "node", "server"]
    assert repaired["beats"][0]["action"] == "reveal"
    assert repaired["beats"][1]["action"] == "highlight"
    assert repaired["beats"][2]["action"] == "connect"
