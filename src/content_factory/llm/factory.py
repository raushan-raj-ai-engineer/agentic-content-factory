from __future__ import annotations

from dataclasses import dataclass

from content_factory.config.settings import Settings
from content_factory.llm.anthropic import AnthropicLLMProvider
from content_factory.llm.base import LLMProvider
from content_factory.llm.gemini import GeminiLLMProvider
from content_factory.llm.failover import RuntimeFailoverLLMProvider
from content_factory.llm.local import LocalLLMProvider
from content_factory.llm.openai_compatible import (
    OpenAICompatibleLLMProvider,
    OpenAILLMProvider,
)

_SUPPORTED = {"auto", "ollama", "gemini", "openai", "anthropic", "compatible"}


@dataclass(frozen=True)
class LLMSelection:
    provider: LLMProvider
    requested_provider: str
    provider_name: str
    model_name: str
    selection_mode: str
    fallback_from: str | None = None
    fallback_reason: str | None = None


async def select_llm_provider(
    settings: Settings,
    *,
    provider_override: str | None = None,
    model_override: str | None = None,
) -> LLMSelection:
    """Select the primary provider/model and configure bounded runtime fallback.

    ``auto`` may try providers in ``LLM_FALLBACK_ORDER`` before the workflow
    starts. When ``LLM_OLLAMA_FALLBACK=true`` and the primary is a cloud
    provider, retryable runtime failures can switch once to Ollama; all later
    text-agent calls stay on that local provider/model.
    """
    requested = (provider_override or settings.llm_provider or "auto").strip().lower()
    if requested not in _SUPPORTED:
        raise RuntimeError(
            f"Unsupported LLM provider {requested!r}. "
            "Use auto, ollama, gemini, openai, anthropic, or compatible."
        )

    if requested != "auto":
        provider: LLMProvider | None = None
        try:
            provider = _build_provider(
                requested,
                settings,
                model_override=model_override,
            )
            await provider.prepare()
            selected_provider: LLMProvider = provider
            if requested != "ollama" and settings.llm_ollama_fallback:
                selected_provider = RuntimeFailoverLLMProvider(
                    provider,
                    _build_ollama_auto_fallback(settings),
                )
            return LLMSelection(
                provider=selected_provider,
                requested_provider=requested,
                provider_name=provider.provider_name,
                model_name=provider.model_name,
                selection_mode="explicit",
            )
        except RuntimeError as exc:
            if provider is not None:
                await provider.release()
            if requested == "ollama" or not settings.llm_ollama_fallback:
                raise

            fallback = _build_ollama_auto_fallback(settings)
            try:
                await fallback.prepare()
            except RuntimeError as fallback_exc:
                await fallback.release()
                raise RuntimeError(
                    f"Requested LLM provider {requested!r} could not start: {exc}. "
                    f"Ollama auto fallback also failed: {fallback_exc}"
                ) from fallback_exc

            return LLMSelection(
                provider=fallback,
                requested_provider=requested,
                provider_name=fallback.provider_name,
                model_name=fallback.model_name,
                selection_mode="fallback-to-ollama",
                fallback_from=requested,
                fallback_reason=str(exc),
            )

    order = _fallback_order(settings.llm_fallback_order)
    errors: list[str] = []
    for name in order:
        provider: LLMProvider | None = None
        try:
            provider = _build_provider(
                name,
                settings,
                model_override=model_override,
                auto_mode=True,
            )
            await provider.prepare()
            selected_provider: LLMProvider = provider
            if name != "ollama" and settings.llm_ollama_fallback:
                selected_provider = RuntimeFailoverLLMProvider(
                    provider,
                    _build_ollama_auto_fallback(settings),
                )
            return LLMSelection(
                provider=selected_provider,
                requested_provider="auto",
                provider_name=provider.provider_name,
                model_name=provider.model_name,
                selection_mode="auto",
            )
        except RuntimeError as exc:
            errors.append(f"{name}: {exc}")
            if provider is not None:
                await provider.release()

    joined = "\n  - ".join(errors) if errors else "No providers were attempted."
    raise RuntimeError(
        "LLM_PROVIDER=auto could not lock an available provider.\n"
        f"  - {joined}\n"
        "Configure at least one provider in .env."
    )



def _build_ollama_auto_fallback(settings: Settings) -> LocalLLMProvider:
    """Build the last-resort local provider with model discovery forced to auto.

    Cloud model overrides must never leak into the local fallback. Ollama will
    inspect ``/api/tags`` and choose the best installed Qwen/Llama model.
    """
    return LocalLLMProvider(
        model="auto",
        base_url=settings.ollama_base_url or settings.llm_base_url,
        timeout=settings.llm_timeout,
    )

def _fallback_order(raw: str) -> list[str]:
    result: list[str] = []
    for item in str(raw or "").split(","):
        name = item.strip().lower()
        if not name or name == "auto" or name not in _SUPPORTED or name in result:
            continue
        result.append(name)
    return result or ["ollama", "gemini", "openai", "anthropic", "compatible"]


def _model_override(
    *,
    provider_name: str,
    provider_model: str,
    legacy_model: str,
    cli_model: str | None,
    auto_mode: bool,
) -> str:
    if cli_model and cli_model.strip() and cli_model.strip().lower() != "auto":
        return cli_model.strip()
    if provider_model.strip() and provider_model.strip().lower() != "auto":
        return provider_model.strip()
    if not auto_mode and legacy_model.strip() and legacy_model.strip().lower() != "auto":
        return legacy_model.strip()
    if provider_name == "ollama":
        return provider_model.strip() or legacy_model.strip() or "auto"
    return ""


def _build_provider(
    name: str,
    settings: Settings,
    *,
    model_override: str | None,
    auto_mode: bool = False,
) -> LLMProvider:
    timeout = settings.llm_timeout

    if name == "ollama":
        model = _model_override(
            provider_name=name,
            provider_model=settings.ollama_model,
            legacy_model=settings.llm_model,
            cli_model=model_override,
            auto_mode=auto_mode,
        ) or "auto"
        return LocalLLMProvider(
            model=model,
            base_url=settings.ollama_base_url or settings.llm_base_url,
            timeout=timeout,
        )

    if name == "gemini":
        model = _model_override(
            provider_name=name,
            provider_model=settings.gemini_model,
            legacy_model=settings.llm_model,
            cli_model=model_override,
            auto_mode=auto_mode,
        )
        api_key = settings.gemini_api_key or (
            settings.llm_api_key
            if not auto_mode or settings.llm_provider == "gemini"
            else ""
        )
        if not api_key or not model:
            raise RuntimeError(
                "Gemini is not fully configured; set GEMINI_API_KEY and GEMINI_MODEL."
            )
        return GeminiLLMProvider(
            model=model,
            api_key=api_key,
            base_url=settings.gemini_base_url,
            timeout=timeout,
        )

    if name == "openai":
        model = _model_override(
            provider_name=name,
            provider_model=settings.openai_model,
            legacy_model=settings.llm_model,
            cli_model=model_override,
            auto_mode=auto_mode,
        )
        api_key = settings.openai_api_key or (
            settings.llm_api_key
            if not auto_mode or settings.llm_provider == "openai"
            else ""
        )
        if not api_key or not model:
            raise RuntimeError(
                "OpenAI is not fully configured; set OPENAI_API_KEY and OPENAI_MODEL."
            )
        return OpenAILLMProvider(
            model=model,
            api_key=api_key,
            base_url=settings.openai_base_url,
            timeout=timeout,
        )

    if name == "anthropic":
        model = _model_override(
            provider_name=name,
            provider_model=settings.anthropic_model,
            legacy_model=settings.llm_model,
            cli_model=model_override,
            auto_mode=auto_mode,
        )
        api_key = settings.anthropic_api_key or (
            settings.llm_api_key
            if not auto_mode or settings.llm_provider == "anthropic"
            else ""
        )
        if not api_key or not model:
            raise RuntimeError(
                "Anthropic is not fully configured; set ANTHROPIC_API_KEY and "
                "ANTHROPIC_MODEL."
            )
        return AnthropicLLMProvider(
            model=model,
            api_key=api_key,
            base_url=settings.anthropic_base_url,
            timeout=timeout,
        )

    if name == "compatible":
        model = _model_override(
            provider_name=name,
            provider_model=settings.compatible_model,
            legacy_model=settings.llm_model,
            cli_model=model_override,
            auto_mode=auto_mode,
        )
        if not settings.compatible_base_url or not model:
            raise RuntimeError(
                "OpenAI-compatible provider is not fully configured; set "
                "LLM_COMPATIBLE_BASE_URL and LLM_COMPATIBLE_MODEL."
            )
        return OpenAICompatibleLLMProvider(
            model=model,
            api_key=settings.compatible_api_key or (
                settings.llm_api_key
                if not auto_mode or settings.llm_provider == "compatible"
                else ""
            ),
            base_url=settings.compatible_base_url,
            timeout=timeout,
            provider_name="compatible",
        )

    raise RuntimeError(f"Unsupported LLM provider: {name}")
