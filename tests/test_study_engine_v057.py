from __future__ import annotations

import asyncio
import math
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from content_factory.agents.retention_optimizer import RetentionOptimizerAgent
from content_factory.agents.study_animation_director import StudyAnimationDirectorAgent
from content_factory.video.local import LocalVideoAssembler
from content_factory.visual.study_storyboard import StudySceneStoryboard, StudyVisualBeat, StudyVisualObject


def test_informative_hook_rejects_generic_question() -> None:
    assert not RetentionOptimizerAgent._informative_study_hook(
        "Have you ever wondered how models connect to external data sources?"
    )
    assert RetentionOptimizerAgent._informative_study_hook(
        "Large language models cannot read local files directly; MCP standardizes the connection without custom glue for every tool."
    )


def test_temporal_alignment_removes_early_security_scene() -> None:
    scene = SimpleNamespace(
        id=2,
        title="Context",
        description=(
            "AI applications need custom integrations to connect models to local files, "
            "databases, and external data sources. MCP provides a standard interface."
        ),
    )
    sb = StudySceneStoryboard(
        scene_id=2,
        purpose="Show a validation boundary",
        layout="boundary",
        objects=[
            StudyVisualObject(id="request", kind="packet", label="Request", slot="left_mid"),
            StudyVisualObject(id="gate", kind="gate", label="Validation Boundary", slot="center"),
            StudyVisualObject(id="allowed", kind="resource", label="Allowed", slot="right_top"),
            StudyVisualObject(id="blocked", kind="shield", label="Blocked", slot="right_bottom"),
        ],
        beats=[
            StudyVisualBeat(cue="custom integrations", action="reveal", target="request"),
            StudyVisualBeat(cue="connect models", action="reveal", target="gate"),
            StudyVisualBeat(cue="local files", action="reject", target="gate", source="request", destination="blocked"),
            StudyVisualBeat(cue="standard interface", action="allow", target="gate", source="request", destination="allowed"),
        ],
    )
    repaired = StudyAnimationDirectorAgent._repair_temporal_alignment(sb, scene, "Model Context Protocol MCP")
    kinds = {obj.kind for obj in repaired.objects}
    actions = {beat.action for beat in repaired.beats}
    assert "gate" not in kinds
    assert "shield" not in kinds
    assert "reject" not in actions
    assert kinds & {"model", "connector", "resource"}


def test_mcp_fallback_does_not_use_math_primitives_for_function_word() -> None:
    scene = SimpleNamespace(
        id=6,
        title="Implementation",
        description=(
            "The server maps a request to a local function and returns the result "
            "through the Model Context Protocol client."
        ),
        key_elements=["server", "request", "function", "client"],
        visual_type="technical_workflow",
    )
    sb = StudyAnimationDirectorAgent._fallback("Model Context Protocol MCP", scene)
    kinds = {obj.kind for obj in sb.objects}
    assert not (kinds & {"equation", "number_line", "shape"})


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_final_audio_mastering_reaches_loudness_target(tmp_path: Path) -> None:
    source = tmp_path / "quiet.mp4"
    # Quiet sine tone gives deterministic loudness that must be boosted substantially.
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=black:s=320x180:r=30:d=3",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
            "-filter:a", "volume=0.03",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", str(source),
        ],
        check=True,
    )
    assembler = LocalVideoAssembler()
    before = asyncio.run(assembler._measure_loudness(source))
    asyncio.run(assembler._master_study_audio(source))
    after = asyncio.run(assembler._measure_loudness(source))
    assert before["input_i"] < -20
    assert math.isclose(after["input_i"], -16.0, abs_tol=1.3)
    assert after["input_tp"] <= -1.15
