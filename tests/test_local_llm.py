import pytest

from content_factory.llm.local import LocalLLMProvider


@pytest.mark.asyncio
async def test_local_llm_provider() -> None:
    provider = LocalLLMProvider(
        model="qwen3:8b",
    )

    response = await provider.generate(
        "Explain AI agents in one sentence.",
    )

    assert response
    assert isinstance(response, str)
