from __future__ import annotations

import pytest

from content_factory.agents.script_writer import ScriptWriterAgent
from content_factory.agents.strategy_grounding import StrategyGroundingAgent
from content_factory.models.content import ContentStrategy, YouTubeScript
from content_factory.orchestration.state import WorkflowState
from content_factory.voice.local import LocalVoiceProvider


def _strategy(minutes: int = 14) -> ContentStrategy:
    return ContentStrategy(
        topic="Model Context Protocol MCP",
        audience="beginner developers",
        angle="Teach MCP from first principles with implementation and verification",
        hook="How does MCP work?",
        content_type="Educational Study Video",
        estimated_duration_minutes=minutes,
    )


@pytest.mark.asyncio
async def test_user_duration_override_wins_over_strategy() -> None:
    state = WorkflowState(run_id="duration-user", topic="Model Context Protocol MCP")
    state.metadata["content_mode"] = "study"
    state.metadata["requested_duration_minutes"] = 10
    state.strategy = _strategy(14)

    result = await StrategyGroundingAgent().execute(state)

    assert result.strategy is not None
    assert result.strategy.estimated_duration_minutes == 10
    assert result.metadata["topic_grounding"]["target_duration_minutes"] == 10
    assert result.metadata["topic_grounding"]["duration_source"] == "user"


@pytest.mark.asyncio
async def test_strategy_duration_remains_default_without_override() -> None:
    state = WorkflowState(run_id="duration-strategy", topic="Model Context Protocol MCP")
    state.metadata["content_mode"] = "study"
    state.strategy = _strategy(14)

    result = await StrategyGroundingAgent().execute(state)

    assert result.strategy is not None
    assert result.strategy.estimated_duration_minutes == 14
    assert result.metadata["topic_grounding"]["target_duration_minutes"] == 14
    assert result.metadata["topic_grounding"]["duration_source"] == "strategy"


def test_auto_us_study_voice_prefers_kokoro_when_ready() -> None:
    provider = object.__new__(LocalVoiceProvider)
    provider._preferred_voice = ""
    provider._preferred_backend = "auto"
    provider._voice_profile = "us-male-warm"
    provider._kokoro_available = True
    provider._kokoro_voice_male = "am_michael"
    provider._kokoro_voice_female = "af_bella"
    provider._piper_models = []
    provider._system_voices = []

    assert provider._pick_narrator("en_US") == ("kokoro", "am_michael", None)


def test_clear_female_profile_prefers_kokoro_bella_when_ready() -> None:
    provider = object.__new__(LocalVoiceProvider)
    provider._preferred_voice = ""
    provider._preferred_backend = "auto"
    provider._voice_profile = "us-female-clear"
    provider._kokoro_available = True
    provider._kokoro_voice_male = "am_michael"
    provider._kokoro_voice_female = "af_bella"
    provider._piper_models = []
    provider._system_voices = []

    assert provider._pick_narrator("en_US") == ("kokoro", "af_bella", None)


class _ExpansionLLM:
    async def generate_structured(self, prompt, model, **kwargs):
        if model.__name__ != "_TargetedExpansion":
            raise AssertionError(model)
        return model(
            additions=[
                {
                    "section_title": "Implementation",
                    "added_narration": " ".join(["detail"] * 420),
                }
            ]
        )


@pytest.mark.asyncio
async def test_targeted_expansion_adds_depth_without_full_rewrite() -> None:
    state = WorkflowState(run_id="depth", topic="Model Context Protocol MCP")
    state.metadata["content_mode"] = "study"
    state.strategy = _strategy(14)
    script = YouTubeScript(
        title="MCP",
        hook=" ".join(["hook"] * 20),
        introduction=" ".join(["intro"] * 100),
        sections=[
            {"title": "Concept", "content": " ".join(["concept"] * 450)},
            {"title": "Implementation", "content": " ".join(["code"] * 300)},
            {"title": "Verification", "content": " ".join(["verify"] * 400)},
        ],
        conclusion=" ".join(["conclusion"] * 70),
        call_to_action=" ".join(["practice"] * 20),
        estimated_duration_minutes=14,
    )
    before = ScriptWriterAgent._word_count(script)
    agent = ScriptWriterAgent(_ExpansionLLM())

    result = await agent._targeted_expand_study_script(
        state=state,
        script=script,
        missing_words=420,
    )

    after = ScriptWriterAgent._word_count(result)
    assert after > before
    assert result.sections[0].content.startswith("concept")
    assert result.sections[1].content.startswith("code")
    assert "detail detail" in result.sections[1].content
