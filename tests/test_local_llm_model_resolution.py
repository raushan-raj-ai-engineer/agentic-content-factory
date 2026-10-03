import pytest

from content_factory.llm.local import LocalLLMProvider


class FakeResponse:
    is_error = False
    status_code = 200
    text = ""

    def __init__(self, names):
        self._names = names

    def json(self):
        return {"models": [{"name": name} for name in self._names]}


class FakeClient:
    def __init__(self, names):
        self._names = names

    async def get(self, url):
        return FakeResponse(self._names)


@pytest.mark.asyncio
async def test_missing_configured_model_falls_back_to_installed_qwen(monkeypatch):
    provider = LocalLLMProvider(model="qwen2.5:3b")

    async def fake_client():
        return FakeClient(["llama3.2:3b", "qwen3:4b"])

    monkeypatch.setattr(provider, "_get_client", fake_client)
    await provider._ensure_model_available()
    assert provider._model == "qwen3:4b"


@pytest.mark.asyncio
async def test_auto_model_uses_installed_llama_when_qwen_is_absent(monkeypatch):
    provider = LocalLLMProvider(model="auto")

    async def fake_client():
        return FakeClient(["llama3.2:3b"])

    monkeypatch.setattr(provider, "_get_client", fake_client)
    await provider._ensure_model_available()
    assert provider._model == "llama3.2:3b"


@pytest.mark.asyncio
async def test_strict_model_mode_keeps_explicit_failure(monkeypatch):
    provider = LocalLLMProvider(model="qwen2.5:3b")

    async def fake_client():
        return FakeClient(["llama3.2:3b"])

    monkeypatch.setattr(provider, "_get_client", fake_client)
    monkeypatch.setenv("CONTENT_FACTORY_STRICT_LLM_MODEL", "1")
    with pytest.raises(RuntimeError, match="not installed"):
        await provider._ensure_model_available()
