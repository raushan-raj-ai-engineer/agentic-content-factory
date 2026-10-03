from pathlib import Path

import pytest

from content_factory.agents.study_localization import (
    StudyLocalizationAgent,
    localization_fields,
    normalize_locale,
)
from content_factory.orchestration.state import WorkflowState
from content_factory.voice.local import (
    LocalVoiceProvider,
    PiperModelInfo,
    SystemVoiceInfo,
)


def test_locale_normalization_accepts_bcp47_and_python_style():
    assert normalize_locale("en-US") == "en_US"
    assert normalize_locale("en_us") == "en_US"
    assert normalize_locale("hi-IN") == "hi_IN"


def test_us_localization_fields_are_explicit():
    fields = localization_fields("en-US")
    assert fields["target_language"] == "en"
    assert fields["target_language_name"] == "English (United States)"
    assert fields["target_market_geo"] == "US"
    assert fields["target_locale"] == "en_US"


@pytest.mark.asyncio
async def test_study_mode_defaults_to_us_english():
    state = WorkflowState(run_id="x")
    state.metadata["content_mode"] = "study"
    await StudyLocalizationAgent().execute(state)
    assert state.metadata["target_locale"] == "en_US"
    assert state.metadata["target_market_geo"] == "US"
    assert state.metadata["localization_source"] == "study-default"


@pytest.mark.asyncio
async def test_user_locale_override_wins_in_study_mode():
    state = WorkflowState(run_id="x")
    state.metadata.update(
        {
            "content_mode": "study",
            "requested_locale": "en-GB",
        }
    )
    await StudyLocalizationAgent().execute(state)
    assert state.metadata["target_locale"] == "en_GB"
    assert state.metadata["target_market_geo"] == "GB"
    assert state.metadata["localization_source"] == "user"


def _fake_provider() -> LocalVoiceProvider:
    provider = LocalVoiceProvider.__new__(LocalVoiceProvider)
    provider._preferred_voice = ""
    provider._voice_profile = "us-male-warm"
    provider._piper_models = [
        PiperModelInfo(
            key="en_US-lessac-medium",
            model_path=Path("lessac.onnx"),
            config_path=Path("lessac.json"),
            locale="en_US",
            language_family="en",
            num_speakers=1,
            speaker_ids=(0,),
        ),
        PiperModelInfo(
            key="en_US-ryan-medium",
            model_path=Path("ryan.onnx"),
            config_path=Path("ryan.json"),
            locale="en_US",
            language_family="en",
            num_speakers=1,
            speaker_ids=(0,),
        ),
    ]
    provider._system_voices = [SystemVoiceInfo(name="Alex", locale="en_US")]
    return provider


def test_us_male_profile_prefers_ryan_over_other_us_piper_voice():
    provider = _fake_provider()
    assert provider._pick_narrator("en_US") == (
        "piper",
        "en_US-ryan-medium",
        0,
    )


def test_exact_voice_choice_overrides_profile():
    provider = _fake_provider()
    provider._preferred_voice = "en_US-lessac-medium"
    assert provider._pick_narrator("en_US") == (
        "piper",
        "en_US-lessac-medium",
        0,
    )


def test_study_voice_profile_targets_readable_educational_pace():
    from content_factory.voice.director import VoiceDirector

    director = VoiceDirector(language_override="en_US")
    profile = director.profile_for(
        text="The client sends a request to the server and validates the response.",
        audience="software developers learning a technical tutorial",
        topic="Model Context Protocol MCP tutorial",
        segment_index=5,
        total_segments=12,
    )
    assert 138 <= profile.rate_wpm <= 145
    assert profile.length_scale >= 1.16
