import pytest

from content_factory.config.settings import Settings
from content_factory.llm.factory import select_llm_provider
from content_factory.llm.gemini import GeminiLLMProvider
from content_factory.llm.failover import RuntimeFailoverLLMProvider
from content_factory.llm.local import LocalLLMProvider
from content_factory.llm.openai_compatible import OpenAILLMProvider


@pytest.mark.asyncio
async def test_auto_selection_falls_back_before_lock_when_ollama_is_unavailable(
    monkeypatch,
) -> None:
    settings = Settings(
        llm_provider="auto",
        llm_fallback_order="ollama,gemini",
        ollama_model="auto",
        gemini_api_key="test-key",
        gemini_model="test-gemini-model",
    )

    async def unavailable(self) -> None:
        raise RuntimeError("ollama unavailable")

    async def gemini_ready(self) -> None:
        return None

    monkeypatch.setattr(LocalLLMProvider, "prepare", unavailable)
    monkeypatch.setattr(GeminiLLMProvider, "prepare", gemini_ready)

    selection = await select_llm_provider(settings)

    assert selection.provider_name == "gemini"
    assert selection.model_name == "test-gemini-model"
    assert selection.selection_mode == "auto"
    assert isinstance(selection.provider, RuntimeFailoverLLMProvider)
    assert selection.provider.provider_name == "gemini"


@pytest.mark.asyncio
async def test_explicit_provider_is_selected_once_with_cli_model_override() -> None:
    settings = Settings(
        llm_provider="auto",
        openai_api_key="test-key",
        openai_model="configured-model",
    )

    selection = await select_llm_provider(
        settings,
        provider_override="openai",
        model_override="cli-model",
    )

    assert isinstance(selection.provider, RuntimeFailoverLLMProvider)
    assert selection.provider.provider_name == "openai"
    assert selection.provider_name == "openai"
    assert selection.model_name == "cli-model"
    assert selection.selection_mode == "explicit"


@pytest.mark.asyncio
async def test_auto_does_not_use_ambiguous_generic_model_for_cloud_provider(
    monkeypatch,
) -> None:
    settings = Settings(
        llm_provider="auto",
        llm_model="some-generic-model",
        llm_fallback_order="ollama,gemini",
        gemini_api_key="test-key",
        gemini_model="",
    )

    async def unavailable(self) -> None:
        raise RuntimeError("ollama unavailable")

    monkeypatch.setattr(LocalLLMProvider, "prepare", unavailable)

    with pytest.raises(RuntimeError, match="could not lock an available provider"):
        await select_llm_provider(settings)


@pytest.mark.asyncio
async def test_explicit_gemini_missing_config_falls_back_to_ollama_auto(monkeypatch) -> None:
    settings = Settings(
        llm_provider="gemini",
        gemini_api_key="",
        gemini_model="",
        ollama_model="some-stale-cloud-model",
        llm_ollama_fallback=True,
    )

    async def local_ready(self) -> None:
        assert self._requested_model == "auto"
        self._model = "qwen3:4b-instruct"
        self._model_checked = True

    monkeypatch.setattr(LocalLLMProvider, "prepare", local_ready)

    selection = await select_llm_provider(settings)

    assert selection.provider_name == "ollama"
    assert selection.model_name == "qwen3:4b-instruct"
    assert selection.selection_mode == "fallback-to-ollama"
    assert selection.fallback_from == "gemini"
    assert "Gemini is not fully configured" in (selection.fallback_reason or "")


@pytest.mark.asyncio
async def test_explicit_cloud_prepare_failure_falls_back_to_ollama_auto(monkeypatch) -> None:
    settings = Settings(
        llm_provider="gemini",
        gemini_api_key="test-key",
        gemini_model="test-gemini-model",
        ollama_model="qwen2.5:3b",
        llm_ollama_fallback=True,
    )

    async def gemini_unavailable(self) -> None:
        raise RuntimeError("gemini startup unavailable")

    async def local_ready(self) -> None:
        assert self._requested_model == "auto"
        self._model = "llama3.2:latest"
        self._model_checked = True

    monkeypatch.setattr(GeminiLLMProvider, "prepare", gemini_unavailable)
    monkeypatch.setattr(LocalLLMProvider, "prepare", local_ready)

    selection = await select_llm_provider(settings)

    assert selection.provider_name == "ollama"
    assert selection.model_name == "llama3.2:latest"
    assert selection.fallback_from == "gemini"


@pytest.mark.asyncio
async def test_explicit_provider_failure_is_strict_when_ollama_fallback_disabled() -> None:
    settings = Settings(
        llm_provider="gemini",
        gemini_api_key="",
        gemini_model="",
        llm_ollama_fallback=False,
    )

    with pytest.raises(RuntimeError, match="Gemini is not fully configured"):
        await select_llm_provider(settings)
