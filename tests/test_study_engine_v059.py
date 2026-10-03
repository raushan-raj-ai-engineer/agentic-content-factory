from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from content_factory.agents.study_animation_director import StudyAnimationDirectorAgent
from content_factory.video.local import LocalVideoAssembler


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_visual_qc_does_not_treat_dark_panel_fill_as_unreadable(tmp_path: Path) -> None:
    video = tmp_path / "dark_panel_readable.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
        (
            "color=c=0x07111F:s=320x180:r=30:d=4,"
            "drawbox=x=35:y=28:w=250:h=124:color=0x1b2c43:t=fill,"
            "drawbox=x=35:y=28:w=250:h=124:color=0x7DD3FC:t=3,"
            "drawbox=x=70:y=65:w=180:h=8:color=0xF8FAFC:t=fill,"
            "drawbox=x=90:y=95:w=140:h=6:color=0xE2E8F0:t=fill"
        ),
        "-pix_fmt", "yuv420p", str(video),
    ], check=True)
    assembler = LocalVideoAssembler()
    metrics = asyncio.run(assembler._study_visual_metrics(video))
    assert metrics["edge_luma"] >= 50
    asyncio.run(assembler._validate_study_visual_readability(video))


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_visual_qc_auto_repairs_contrast_only_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = tmp_path / "dim_but_filled.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
        (
            "color=c=0x07111F:s=320x180:r=30:d=4,"
            "drawbox=x=30:y=25:w=260:h=130:color=0x1b2c43:t=fill,"
            "drawbox=x=30:y=25:w=260:h=130:color=0x405060:t=3,"
            "drawbox=x=70:y=68:w=180:h=7:color=0x405060:t=fill,"
            "drawbox=x=90:y=100:w=140:h=6:color=0x405060:t=fill"
        ),
        "-pix_fmt", "yuv420p", str(video),
    ], check=True)
    monkeypatch.setenv("STUDY_MIN_EDGE_LUMA", "70")
    monkeypatch.setenv("STUDY_MIN_P10_EDGE_RATIO", "0.001")
    monkeypatch.setenv(
        "STUDY_VISUAL_CONTRAST_FILTER",
        "eq=contrast=1.12:brightness=0.10:saturation=1.06:gamma=1.04",
    )
    assembler = LocalVideoAssembler()
    before = asyncio.run(assembler._study_visual_metrics(video))
    assert before["p10_occupancy"] > 0.0075
    assert before["edge_luma"] < 70
    asyncio.run(assembler._validate_study_visual_readability(video))
    after = asyncio.run(assembler._study_visual_metrics(video))
    assert after["edge_luma"] >= 70


def test_renderer_palette_and_focus_are_high_contrast() -> None:
    source = Path("src/content_factory/visual/study_manim_scene.py").read_text(encoding="utf-8")
    assert 'PANEL = "#18304D"' in source
    assert 'PANEL_2 = "#23405F"' in source
    assert 'MUTED = "#E2E8F0"' in source
    assert 'TEXT = "#F8FAFC"' in source
    assert "else 0.76" in source


def test_storyboard_batch_size_uses_five_scene_default_with_env_override() -> None:
    assert StudyAnimationDirectorAgent.BATCH_SIZE == 5
    source = Path("src/content_factory/agents/study_animation_director.py").read_text(encoding="utf-8")
    assert "STUDY_STORYBOARD_BATCH_SIZE" in source
    assert "min(6" in source
