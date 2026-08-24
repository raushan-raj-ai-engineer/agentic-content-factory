from content_factory.config.settings import Settings


def test_settings_loads_environment_variables(
    monkeypatch,
) -> None:
    """Settings should load application environment variables."""
    monkeypatch.setenv(
        "YOUTUBE_API_KEY",
        "apikey",
    )
    monkeypatch.setenv(
        "YOUTUBE_MAX_RESULTS",
        "10",
    )
    monkeypatch.setenv(
        "YOUTUBE_TIMEOUT",
        "30",
    )
    monkeypatch.setenv(
        "LLM_PROVIDER",
        "ollama",
    )
    monkeypatch.setenv(
        "LLM_MODEL",
        "qwen2.5:3b",
    )
    monkeypatch.setenv(
        "LLM_BASE_URL",
        "http://localhost:11434",
    )
    monkeypatch.setenv(
        "LLM_TIMEOUT",
        "120",
    )

    settings = Settings()

    assert settings.youtube_api_key == "apikey"
    assert settings.youtube_max_results == 10
    assert settings.youtube_timeout == 30.0
    assert settings.llm_provider == "ollama"
    assert settings.llm_model == "qwen2.5:3b"
    assert settings.llm_base_url == "http://localhost:11434"
    assert settings.llm_timeout == 120.0
