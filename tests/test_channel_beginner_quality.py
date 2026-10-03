from pathlib import Path
import shutil
import subprocess

import pytest

from content_factory.channel.catalog import lesson
from content_factory.channel.pedagogy import sme_review
from content_factory.channel.render import render


def test_binary_search_has_beginner_theory_before_trace():
    item = lesson("binary-search")
    stages = [scene.stage for scene in item.scenes]
    assert "theory" in stages
    assert stages.index("theory") < stages.index("trace")
    assert "What is binary search?" in [scene.title for scene in item.scenes]
    assert sme_review(item)["passed"] is True


def test_cards_renderer_has_no_full_black_flash(tmp_path: Path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg is required")
    scene = lesson("binary-search").scenes[1]
    spec = scene.__dict__.copy()
    spec.update(index=1, total=3, seconds=6.0)
    output = tmp_path / "scene.mp4"
    render(spec, tmp_path / "work", output, "cards")
    proc = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-i", str(output),
            "-vf", "blackdetect=d=0.03:pic_th=0.98:pix_th=0.10",
            "-an", "-f", "null", "-",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    assert "black_start:" not in proc.stderr
