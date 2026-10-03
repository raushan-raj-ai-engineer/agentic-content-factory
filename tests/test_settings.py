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


def test_yaml_llm_defaults_are_overridden_by_environment(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-model-from-env")

    settings = Settings.from_yaml("configs/local.yaml")

    assert settings.llm_provider == "gemini"
    assert settings.gemini_api_key == "gemini-key"
    assert settings.gemini_model == "gemini-model-from-env"


def test_from_yaml_loads_project_dotenv_before_yaml_defaults(tmp_path, monkeypatch) -> None:
    project = tmp_path / "project"
    configs = project / "configs"
    configs.mkdir(parents=True)
    (configs / "local.yaml").write_text(
        "llm:\n  provider: auto\n  gemini:\n    model: yaml-model\n",
        encoding="utf-8",
    )
    (project / ".env").write_text(
        "LLM_PROVIDER=gemini\nGEMINI_API_KEY=test-key\nGEMINI_MODEL=gemini-dotenv-model\n",
        encoding="utf-8",
    )
    for name in ("LLM_PROVIDER", "GEMINI_API_KEY", "GEMINI_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(project)

    settings = Settings.from_yaml("configs/local.yaml")

    assert settings.llm_provider == "gemini"
    assert settings.gemini_api_key == "test-key"
    assert settings.gemini_model == "gemini-dotenv-model"
