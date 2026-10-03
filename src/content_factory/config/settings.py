from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration."""

    # Kept only for backward compatibility. Local YouTube research does not use it.
    youtube_api_key: str = Field(default="", validation_alias="YOUTUBE_API_KEY")
    youtube_max_results: int = Field(default=20, validation_alias="YOUTUBE_MAX_RESULTS")
    youtube_timeout: float = Field(default=30.0, validation_alias="YOUTUBE_TIMEOUT")
    research_provider: str = Field(default="youtube", validation_alias="RESEARCH_PROVIDER")

    trend_mode: str = "auto"
    trend_topic: str | None = None
    trend_category: str = "technical"
    trend_lookback_days: int = 7

    approval_mode: str = "manual"
    approval_response: str = "y"

    # Primary provider/model is selected before the workflow; optional runtime Ollama failover is one-way.
    llm_provider: str = Field(default="auto", validation_alias="LLM_PROVIDER")
    llm_model: str = Field(default="auto", validation_alias="LLM_MODEL")
    llm_base_url: str = Field(
        default="http://localhost:11434",
        validation_alias="LLM_BASE_URL",
    )
    llm_api_key: str = Field(default="", validation_alias="LLM_API_KEY")
    llm_timeout: float = Field(default=180.0, validation_alias="LLM_TIMEOUT")
    llm_fallback_order: str = Field(
        default="gemini,openai,anthropic,compatible,ollama",
        validation_alias="LLM_FALLBACK_ORDER",
    )
    llm_ollama_fallback: bool = Field(
        default=True,
        validation_alias="LLM_OLLAMA_FALLBACK",
    )

    ollama_model: str = Field(default="auto", validation_alias="OLLAMA_MODEL")
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        validation_alias="OLLAMA_BASE_URL",
    )

    gemini_api_key: str = Field(default="", validation_alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="", validation_alias="GEMINI_MODEL")
    gemini_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta",
        validation_alias="GEMINI_BASE_URL",
    )

    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    openai_model: str = Field(default="", validation_alias="OPENAI_MODEL")
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        validation_alias="OPENAI_BASE_URL",
    )

    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="", validation_alias="ANTHROPIC_MODEL")
    anthropic_base_url: str = Field(
        default="https://api.anthropic.com/v1",
        validation_alias="ANTHROPIC_BASE_URL",
    )

    compatible_api_key: str = Field(
        default="",
        validation_alias="LLM_COMPATIBLE_API_KEY",
    )
    compatible_model: str = Field(
        default="",
        validation_alias="LLM_COMPATIBLE_MODEL",
    )
    compatible_base_url: str = Field(
        default="",
        validation_alias="LLM_COMPATIBLE_BASE_URL",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @classmethod
    def from_yaml(cls, path: str | Path = "configs/local.yaml") -> "Settings":
        """Load YAML defaults while allowing environment variables to win.

        The previous loader passed YAML values as explicit constructor arguments,
        which gave them higher priority than ``.env``/environment variables.
        Provider selection is expected to be environment-driven, so LLM-related
        values are resolved with environment variables first.
        """
        config_path = Path(path)
        _load_project_dotenv(config_path)
        if not config_path.exists():
            return cls()

        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid YAML configuration: {config_path}")

        llm = _section(raw, "llm")
        ollama = _section(llm, "ollama")
        gemini = _section(llm, "gemini")
        openai = _section(llm, "openai")
        anthropic = _section(llm, "anthropic")
        compatible = _section(llm, "compatible")
        research = _section(raw, "research")
        youtube = _section(research, "youtube")
        approval = _section(_section(raw, "human_approval"), "default")

        legacy_model = str(llm.get("model", "auto"))
        legacy_base = str(llm.get("base_url", "http://localhost:11434"))
        generic_model = _env("LLM_MODEL", legacy_model)
        generic_base = _env("LLM_BASE_URL", legacy_base)

        return cls(
            llm_provider=_env("LLM_PROVIDER", str(llm.get("provider", "auto"))),
            llm_model=generic_model,
            llm_base_url=generic_base,
            llm_api_key=_env("LLM_API_KEY", ""),
            llm_timeout=float(_env("LLM_TIMEOUT", str(llm.get("timeout", 180.0)))),
            llm_fallback_order=_env(
                "LLM_FALLBACK_ORDER",
                _string_list(llm.get("fallback_order"))
                or "gemini,openai,anthropic,compatible,ollama",
            ),
            llm_ollama_fallback=_env_bool(
                "LLM_OLLAMA_FALLBACK",
                bool(llm.get("ollama_fallback", True)),
            ),
            ollama_model=_env(
                "OLLAMA_MODEL",
                generic_model
                if os.getenv("LLM_MODEL") is not None
                else str(ollama.get("model", legacy_model)),
            ),
            ollama_base_url=_env(
                "OLLAMA_BASE_URL",
                generic_base
                if os.getenv("LLM_BASE_URL") is not None
                else str(ollama.get("base_url", legacy_base)),
            ),
            gemini_api_key=_env("GEMINI_API_KEY", str(gemini.get("api_key", ""))),
            gemini_model=_env("GEMINI_MODEL", str(gemini.get("model", ""))),
            gemini_base_url=_env(
                "GEMINI_BASE_URL",
                str(
                    gemini.get(
                        "base_url",
                        "https://generativelanguage.googleapis.com/v1beta",
                    )
                ),
            ),
            openai_api_key=_env("OPENAI_API_KEY", str(openai.get("api_key", ""))),
            openai_model=_env("OPENAI_MODEL", str(openai.get("model", ""))),
            openai_base_url=_env(
                "OPENAI_BASE_URL",
                str(openai.get("base_url", "https://api.openai.com/v1")),
            ),
            anthropic_api_key=_env(
                "ANTHROPIC_API_KEY",
                str(anthropic.get("api_key", "")),
            ),
            anthropic_model=_env(
                "ANTHROPIC_MODEL",
                str(anthropic.get("model", "")),
            ),
            anthropic_base_url=_env(
                "ANTHROPIC_BASE_URL",
                str(anthropic.get("base_url", "https://api.anthropic.com/v1")),
            ),
            compatible_api_key=_env(
                "LLM_COMPATIBLE_API_KEY",
                str(compatible.get("api_key", "")),
            ),
            compatible_model=_env(
                "LLM_COMPATIBLE_MODEL",
                str(compatible.get("model", "")),
            ),
            compatible_base_url=_env(
                "LLM_COMPATIBLE_BASE_URL",
                str(compatible.get("base_url", "")),
            ),
            research_provider=str(research.get("provider", "youtube")),
            trend_mode=str(research.get("mode", "auto")),
            trend_topic=_optional_string(research.get("topic")),
            trend_category=str(research.get("category", "technical")),
            trend_lookback_days=int(research.get("lookback_days", 7)),
            youtube_max_results=int(youtube.get("max_results", 20)),
            youtube_timeout=float(youtube.get("timeout", 30.0)),
            approval_mode=str(approval.get("mode", "manual")),
            approval_response=str(approval.get("response", "y")),
        )


def _section(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    return value if isinstance(value, dict) else {}


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value is not None else default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _string_list(value: object) -> str:
    if isinstance(value, list):
        return ",".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str):
        return value.strip()
    return ""


def _load_project_dotenv(config_path: Path) -> None:
    """Load the project .env before YAML defaults are converted to init args.

    BaseSettings normally reads .env itself, but explicit constructor values
    passed by from_yaml have higher priority. Loading .env into os.environ first
    lets the existing _env helper enforce the intended order:
    real shell env > .env > YAML > application defaults.
    """
    candidates = [Path.cwd() / ".env"]
    try:
        candidates.append(config_path.resolve().parent.parent / ".env")
    except OSError:
        pass
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            return
