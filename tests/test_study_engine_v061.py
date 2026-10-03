from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageStat

from content_factory.video.local import LocalVideoAssembler
from content_factory.visual.local import LocalVisualProvider
from content_factory.visual.study_backdrop import StudyBackdropRenderer


class _FakePremium:
    available = True



def test_study_ai_hero_is_opt_in_and_scene_one_only(monkeypatch):
    provider = LocalVisualProvider()
    provider._premium = _FakePremium()  # type: ignore[assignment]

    monkeypatch.delenv("CONTENT_FACTORY_STUDY_AI_HERO", raising=False)
    monkeypatch.setenv("CONTENT_FACTORY_STUDY_HERO_VISUALS", "1")
    assert provider._should_use_ai_study_hero(scene_index=1) is False

    monkeypatch.setenv("CONTENT_FACTORY_STUDY_AI_HERO", "1")
    assert provider._should_use_ai_study_hero(scene_index=1) is True
    assert provider._should_use_ai_study_hero(scene_index=2) is False



def test_deterministic_study_backdrop_is_1080p_and_visually_nonempty(tmp_path: Path):
    output = tmp_path / "scene.png"
    StudyBackdropRenderer().render(
        title="AI Agents",
        description="An agent plans, selects a tool, acts, observes, and continues.",
        visual_type="technical_diagram",
        output_path=str(output),
        topic="AI Agents",
        scene_index=1,
    )
    assert output.is_file()
    image = Image.open(output).convert("RGB")
    assert image.size == (1920, 1080)
    stat = ImageStat.Stat(image.resize((160, 90)))
    assert sum(stat.var) > 100



def test_backdrop_renderer_never_draws_instructional_text():
    source = Path("src/content_factory/visual/study_backdrop.py").read_text(encoding="utf-8")
    assert "draw.text(" not in source
    assert "ImageFont" not in source



def test_study_render_parallel_defaults_to_two(monkeypatch):
    monkeypatch.delenv("CONTENT_FACTORY_STUDY_RENDER_PARALLEL", raising=False)
    assembler = LocalVideoAssembler()
    assert assembler._study_parallel == 2

    monkeypatch.setenv("CONTENT_FACTORY_STUDY_RENDER_PARALLEL", "1")
    assembler = LocalVideoAssembler()
    assert assembler._study_parallel == 1




async def test_study_visual_provider_default_never_calls_diffusion(tmp_path: Path, monkeypatch):
    class PremiumMustNotRun:
        available = True

        async def generate(self, **kwargs):
            raise AssertionError("diffusion must not run in default Study Mode")

        async def release(self):
            return None

    monkeypatch.setenv("CONTENT_FACTORY_STUDY_AI_HERO", "0")
    monkeypatch.setenv("CONTENT_FACTORY_VISUAL_CACHE", str(tmp_path / "cache"))
    provider = LocalVisualProvider()
    provider._premium = PremiumMustNotRun()  # type: ignore[assignment]
    provider.set_context(topic="AI Agents", domain="technical", study_mode=True)
    out = tmp_path / "scene_1.png"
    await provider.generate(
        prompt="AI agent architecture with tool use",
        output_path=str(out),
        title="AI Agents",
        description="An AI agent selects a tool and observes the result.",
        visual_type="technical_diagram",
    )
    assert out.is_file()


def test_visual_generator_marks_study_reference_as_vector_ambient():
    source = Path("src/content_factory/agents/visual_generator.py").read_text(encoding="utf-8")
    assert 'return "hero_ambient" if scene_id == 1 else "vector_ambient"' in source


def test_viewer_titles_remove_batch_suffix_and_generic_context():
    from content_factory.agents.visual_generator import VisualGenerationAgent

    assert VisualGenerationAgent._viewer_title("Defining the AI Agent Mental Model — 1") == "Defining the AI Agent Mental Model"
    assert VisualGenerationAgent._viewer_title("Context — 2") == ""
