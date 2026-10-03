from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from content_factory.agents.study_animation_director import StudyAnimationDirectorAgent
from content_factory.video.local import LocalVideoAssembler
from content_factory.visual.study_storyboard import StudySceneStoryboard, StudyVisualBeat, StudyVisualObject


def test_subject_term_matching_uses_word_boundaries() -> None:
    assert StudyAnimationDirectorAgent._contains_terms("solve an equation", ["equation"])
    assert StudyAnimationDirectorAgent._contains_terms("probability model", ["probability"])
    assert not StudyAnimationDirectorAgent._contains_terms("server function handler", ["fraction", "formula", "matrix"])
    assert not StudyAnimationDirectorAgent._contains_terms("standard integration", ["statistics", "integral"])


def test_mcp_deterministic_repair_stays_technical() -> None:
    scene = SimpleNamespace(
        id=6,
        title="A Simple Mental Model for MCP",
        description=(
            "The smartphone operating system provides a standard interface. "
            "An application requests access to a camera sensor through that interface, "
            "just as an MCP client requests capabilities from a server."
        ),
        key_elements=["smartphone", "operating system", "application", "camera sensor", "MCP client"],
        visual_type="technical_workflow",
    )
    sb = StudyAnimationDirectorAgent._fallback("Model Context Protocol MCP", scene)
    kinds = {obj.kind for obj in sb.objects}
    assert not (kinds & {"equation", "number_line", "shape", "quantity"})
    assert kinds & {"client", "server", "resource", "connector", "person", "place"}


def test_analogy_grounding_replaces_invented_wall_socket() -> None:
    narration = (
        "Think of a smartphone operating system. An application asks to use the camera sensor "
        "through the operating system instead of talking directly to the hardware."
    )
    sb = StudySceneStoryboard(
        scene_id=7,
        purpose="Map a phone analogy to a technical model",
        layout="analogy_map",
        objects=[
            StudyVisualObject(id="real1", kind="place", label="Wall Socket", slot="left_top"),
            StudyVisualObject(id="real2", kind="person", label="Power Plug", slot="left_bottom"),
            StudyVisualObject(id="tech1", kind="host", label="Host", slot="right_top"),
            StudyVisualObject(id="tech2", kind="client", label="Client", slot="right_bottom"),
        ],
        beats=[
            StudyVisualBeat(cue="smartphone operating system", action="reveal", target="real1"),
            StudyVisualBeat(cue="application asks", action="reveal", target="real2"),
            StudyVisualBeat(cue="operating system", action="transform", target="tech1", source="real1"),
            StudyVisualBeat(cue="camera sensor", action="transform", target="tech2", source="real2"),
        ],
    )
    fixed = StudyAnimationDirectorAgent._repair_analogy_grounding(sb, narration)
    labels = {obj.label.lower() for obj in fixed.objects}
    kinds = {obj.kind for obj in fixed.objects}
    assert "wall socket" not in labels
    assert "power plug" not in labels
    assert labels & {"operating system", "smartphone", "application", "camera", "sensor", "hardware sensors"}
    assert kinds & {"device", "app", "sensor"}


def test_renderer_source_has_continuous_scene_prime_and_readable_focus() -> None:
    source = Path("src/content_factory/visual/study_manim_scene.py").read_text(encoding="utf-8")
    assert "def _prime_storyboard_canvas" in source
    assert "def _normalize_storyboard_layout" in source
    assert "else 0.76" in source
    assert 'MUTED = "#E2E8F0"' in source
    assert 'font_size=30' in source


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_visual_qc_rejects_empty_video_and_accepts_mobile_filled_frame(tmp_path: Path) -> None:
    sparse = tmp_path / "sparse.mp4"
    good = tmp_path / "good.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
        "color=c=0x07111F:s=320x180:r=30:d=4", "-pix_fmt", "yuv420p", str(sparse)
    ], check=True)
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
        "color=c=0x07111F:s=320x180:r=30:d=4,drawbox=x=40:y=30:w=240:h=120:color=0xF1F5F9:t=fill",
        "-pix_fmt", "yuv420p", str(good)
    ], check=True)
    assembler = LocalVideoAssembler()
    with pytest.raises(RuntimeError, match="visual readability QC failed"):
        asyncio.run(assembler._validate_study_visual_readability(sparse))
    asyncio.run(assembler._validate_study_visual_readability(good))


def test_code_layout_is_mobile_first_in_renderer_source() -> None:
    source = Path("src/content_factory/visual/study_manim_scene.py").read_text(encoding="utf-8")
    assert 'if layout == "code_plus_state"' in source
    assert "8.8" in source
    assert 'self._code_text(f"{i:>2}  {line_text}", 22' in source
    assert "_sb_code_shells" in source
