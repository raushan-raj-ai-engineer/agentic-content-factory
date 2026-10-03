import pytest

from content_factory.llm.base import LLMProvider
from content_factory.llm.failover import RuntimeFailoverLLMProvider
from content_factory.llm.http_utils import LLMHTTPError


class FakeProvider(LLMProvider):
    def __init__(self, name: str, model: str, *, error: Exception | None = None) -> None:
        super().__init__()
        self._name = name
        self._model = model
        self.error = error
        self.prepared = 0
        self.calls = 0

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def model_name(self) -> str:
        return self._model

    async def prepare(self) -> None:
        self.prepared += 1

    async def generate(self, prompt: str, *, system_prompt: str | None = None) -> str:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return f"{self._name}-ok"


@pytest.mark.asyncio
async def test_runtime_429_switches_to_ollama_and_stays_there() -> None:
    primary = FakeProvider(
        "gemini",
        "gemini-test",
        error=LLMHTTPError(
            provider="gemini",
            model="gemini-test",
            status_code=429,
            body="rate limit",
            url="https://example.invalid",
        ),
    )
    fallback = FakeProvider("ollama", "llama3.2")
    provider = RuntimeFailoverLLMProvider(primary, fallback)

    assert await provider.generate("one") == "ollama-ok"
    assert provider.provider_name == "ollama"
    assert provider.model_name == "llama3.2"
    assert fallback.prepared == 1

    assert await provider.generate("two") == "ollama-ok"
    assert primary.calls == 1
    assert fallback.calls == 2


@pytest.mark.asyncio
async def test_runtime_nonretryable_400_does_not_switch() -> None:
    primary = FakeProvider(
        "gemini",
        "gemini-test",
        error=LLMHTTPError(
            provider="gemini",
            model="gemini-test",
            status_code=400,
            body="bad request",
            url="https://example.invalid",
        ),
    )
    fallback = FakeProvider("ollama", "llama3.2")
    provider = RuntimeFailoverLLMProvider(primary, fallback)

    with pytest.raises(LLMHTTPError):
        await provider.generate("bad")
    assert provider.provider_name == "gemini"
    assert fallback.prepared == 0


@pytest.mark.asyncio
async def test_outer_timeout_can_force_runtime_fallback() -> None:
    primary = FakeProvider("gemini", "gemini-test")
    fallback = FakeProvider("ollama", "qwen3:4b")
    provider = RuntimeFailoverLLMProvider(primary, fallback)

    assert await provider.force_fallback("script chunk timeout") is True
    assert provider.provider_name == "ollama"
    assert await provider.force_fallback("again") is False
