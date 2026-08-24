from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration."""

    # Kept only for backward compatibility. Local YouTube research does not use it.
    youtube_api_key: str = Field(
        default="",
        validation_alias="YOUTUBE_API_KEY",
    )

    youtube_max_results: int = Field(
        default=20,
        validation_alias="YOUTUBE_MAX_RESULTS",
    )

    youtube_timeout: float = Field(
        default=30.0,
        validation_alias="YOUTUBE_TIMEOUT",
    )

    research_provider: str = Field(
        default="youtube",
        validation_alias="RESEARCH_PROVIDER",
    )

    trend_mode: str = "auto"
    trend_topic: str | None = None
    trend_category: str = "technical"
    trend_lookback_days: int = 7

    approval_mode: str = "manual"
    approval_response: str = "y"

    llm_provider: str = Field(
        default="ollama",
        validation_alias="LLM_PROVIDER",
    )

    llm_model: str = Field(
        default="llama3.2",
        validation_alias="LLM_MODEL",
    )

    llm_base_url: str = Field(
        default="http://localhost:11434",
        validation_alias="LLM_BASE_URL",
    )

    llm_timeout: float = Field(
        default=600.0,
        validation_alias="LLM_TIMEOUT",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @classmethod
    def from_yaml(
        cls,
        path: str | Path = "configs/local.yaml",
    ) -> "Settings":
        """Load the local YAML configuration used by the content factory."""
        config_path = Path(path)
        if not config_path.exists():
            return cls()

        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid YAML configuration: {config_path}")

        llm = _section(raw, "llm")
        research = _section(raw, "research")
        youtube = _section(research, "youtube")
        approval = _section(_section(raw, "human_approval"), "default")

        return cls(
            llm_provider=str(llm.get("provider", "ollama")),
            llm_model=str(llm.get("model", "llama3.2")),
            llm_base_url=str(llm.get("base_url", "http://localhost:11434")),
            llm_timeout=float(llm.get("timeout", 600.0)),
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
