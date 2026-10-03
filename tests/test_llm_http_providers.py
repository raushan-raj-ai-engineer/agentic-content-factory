import json
import pytest
from pydantic import BaseModel

from content_factory.llm.anthropic import AnthropicLLMProvider
from content_factory.llm.gemini import GeminiLLMProvider
from content_factory.llm.openai_compatible import OpenAICompatibleLLMProvider


class FakeResponse:
    is_error = False
    status_code = 200
    text = ""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def post(self, url, json):
        self.calls.append((url, json))
        return FakeResponse(self.payload)


class SequencedClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def post(self, url, json):
        self.calls.append((url, json))
        return self.responses.pop(0)


class ErrorResponse(FakeResponse):
    def __init__(self, status_code, text="temporary"):
        super().__init__({"error": text})
        self.status_code = status_code
        self.text = text
        self.is_error = status_code >= 400


class StructuredDemo(BaseModel):
    title: str
    sections: list[str]


@pytest.mark.asyncio
async def test_openai_compatible_generate(monkeypatch) -> None:
    provider = OpenAICompatibleLLMProvider(
        model="demo-model",
        base_url="https://example.test/v1",
        api_key="secret",
    )
    fake = FakeClient({"choices": [{"message": {"content": "hello"}}]})

    async def fake_client():
        return fake

    monkeypatch.setattr(provider, "_get_client", fake_client)
    result = await provider.generate("Say hello", system_prompt="Be concise")

    assert result == "hello"
    assert fake.calls[0][0] == "https://example.test/v1/chat/completions"


@pytest.mark.asyncio
async def test_gemini_generate(monkeypatch) -> None:
    provider = GeminiLLMProvider(model="gemini-test", api_key="secret")
    fake = FakeClient(
        {"candidates": [{"content": {"parts": [{"text": "gemini hello"}]}}]}
    )

    async def fake_client():
        return fake

    monkeypatch.setattr(provider, "_get_client", fake_client)
    result = await provider.generate("Say hello")

    assert result == "gemini hello"
    assert "models/gemini-test:generateContent" in fake.calls[0][0]


@pytest.mark.asyncio
async def test_anthropic_generate(monkeypatch) -> None:
    provider = AnthropicLLMProvider(model="claude-test", api_key="secret")
    fake = FakeClient({"content": [{"type": "text", "text": "anthropic hello"}]})

    async def fake_client():
        return fake

    monkeypatch.setattr(provider, "_get_client", fake_client)
    result = await provider.generate("Say hello")

    assert result == "anthropic hello"
    assert fake.calls[0][0].endswith("/messages")


@pytest.mark.asyncio
async def test_gemini_structured_uses_legacy_generate_content_schema_fields(
    monkeypatch,
) -> None:
    provider = GeminiLLMProvider(model="gemini-test", api_key="secret")
    fake = FakeClient(
        {
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {
                        "parts": [
                            {"text": '{"title":"Demo","sections":["one","two"]}'}
                        ]
                    },
                }
            ]
        }
    )

    async def fake_client():
        return fake

    monkeypatch.setattr(provider, "_get_client", fake_client)
    result = await provider.generate_structured(
        "Create a demo",
        StructuredDemo,
        max_retries=0,
    )

    assert result.title == "Demo"
    generation = fake.calls[0][1]["generationConfig"]
    assert generation["responseMimeType"] == "application/json"
    assert generation["responseJsonSchema"]["type"] == "object"
    assert "responseFormat" not in generation


@pytest.mark.asyncio
async def test_gemini_native_schema_rejection_falls_back_same_model(monkeypatch) -> None:
    provider = GeminiLLMProvider(model="gemini-test", api_key="secret")
    fake = SequencedClient(
        [
            ErrorResponse(400, "Unknown field responseJsonSchema"),
            FakeResponse(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "text": '{"title":"Fallback","sections":["ok"]}'
                                    }
                                ]
                            }
                        }
                    ]
                }
            ),
        ]
    )

    async def fake_client():
        return fake

    monkeypatch.setattr(provider, "_get_client", fake_client)
    result = await provider.generate_structured("Create a demo", StructuredDemo)

    assert result.title == "Fallback"
    assert len(fake.calls) == 2
    assert fake.calls[0][1]["generationConfig"]["responseJsonSchema"]["type"] == "object"
    assert "responseJsonSchema" not in fake.calls[1][1]["generationConfig"]
    assert provider.model_name == "gemini-test"


@pytest.mark.asyncio
async def test_openai_compatible_structured_uses_json_schema(monkeypatch) -> None:
    provider = OpenAICompatibleLLMProvider(
        model="demo-model",
        base_url="https://example.test/v1",
        api_key="secret",
    )
    fake = FakeClient(
        {
            "choices": [
                {
                    "message": {
                        "content": '{"title":"Demo","sections":["one"]}'
                    }
                }
            ]
        }
    )

    async def fake_client():
        return fake

    monkeypatch.setattr(provider, "_get_client", fake_client)
    result = await provider.generate_structured("Create a demo", StructuredDemo)

    assert result.title == "Demo"
    response_format = fake.calls[0][1]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["schema"]["type"] == "object"


@pytest.mark.asyncio
async def test_openai_compatible_schema_rejection_uses_shared_fallback(monkeypatch) -> None:
    provider = OpenAICompatibleLLMProvider(
        model="demo-model",
        base_url="https://example.test/v1",
        api_key="secret",
    )
    fake = SequencedClient(
        [
            ErrorResponse(400, "Unsupported parameter response_format json_schema"),
            FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": '{"title":"Fallback","sections":["ok"]}'
                            }
                        }
                    ]
                }
            ),
        ]
    )

    async def fake_client():
        return fake

    monkeypatch.setattr(provider, "_get_client", fake_client)
    result = await provider.generate_structured("Create a demo", StructuredDemo)

    assert result.title == "Fallback"
    assert len(fake.calls) == 2
    assert "response_format" in fake.calls[0][1]
    assert "response_format" not in fake.calls[1][1]
    assert provider.model_name == "demo-model"


@pytest.mark.asyncio
async def test_anthropic_structured_uses_forced_schema_tool(monkeypatch) -> None:
    provider = AnthropicLLMProvider(model="claude-test", api_key="secret")
    fake = FakeClient(
        {
            "content": [
                {
                    "type": "tool_use",
                    "name": "emit_structured_response",
                    "input": {"title": "Demo", "sections": ["one"]},
                }
            ]
        }
    )

    async def fake_client():
        return fake

    monkeypatch.setattr(provider, "_get_client", fake_client)
    result = await provider.generate_structured("Create a demo", StructuredDemo)

    assert result.title == "Demo"
    payload = fake.calls[0][1]
    assert payload["tools"][0]["input_schema"]["type"] == "object"
    assert payload["tool_choice"]["name"] == "emit_structured_response"


@pytest.mark.asyncio
async def test_anthropic_tool_rejection_uses_shared_fallback(monkeypatch) -> None:
    provider = AnthropicLLMProvider(model="claude-test", api_key="secret")
    fake = SequencedClient(
        [
            ErrorResponse(400, "tool_choice unsupported"),
            FakeResponse(
                {
                    "content": [
                        {
                            "type": "text",
                            "text": '{"title":"Fallback","sections":["ok"]}',
                        }
                    ]
                }
            ),
        ]
    )

    async def fake_client():
        return fake

    monkeypatch.setattr(provider, "_get_client", fake_client)
    result = await provider.generate_structured("Create a demo", StructuredDemo)

    assert result.title == "Fallback"
    assert "tools" in fake.calls[0][1]
    assert "tools" not in fake.calls[1][1]
    assert provider.model_name == "claude-test"


@pytest.mark.asyncio
async def test_shared_http_layer_retries_transient_status_same_model(monkeypatch) -> None:
    provider = GeminiLLMProvider(model="gemini-test", api_key="secret")
    fake = SequencedClient(
        [
            ErrorResponse(503, "busy"),
            FakeResponse({"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}),
        ]
    )

    async def fake_client():
        return fake

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(provider, "_get_client", fake_client)
    monkeypatch.setattr("content_factory.llm.http_utils.asyncio.sleep", no_sleep)
    monkeypatch.setenv("LLM_HTTP_RETRIES", "2")
    monkeypatch.delenv("GEMINI_HTTP_RETRIES", raising=False)

    result = await provider.generate("hello")

    assert result == "ok"
    assert len(fake.calls) == 2
    assert provider.stats()["transient_retries"] == 1

@pytest.mark.asyncio
async def test_ollama_structured_uses_schema_format(monkeypatch) -> None:
    from content_factory.llm.local import LocalLLMProvider

    provider = LocalLLMProvider(model="qwen-test")
    provider._model_checked = True
    provider._model = "qwen-test"
    seen = {}

    async def fake_post(payload):
        seen.update(payload)
        return {"response": '{"title":"Demo","sections":["one"]}'}

    monkeypatch.setattr(provider, "_post_generate", fake_post)
    result = await provider.generate_structured("Create a demo", StructuredDemo)

    assert result.title == "Demo"
    assert seen["format"]["type"] == "object"
    assert seen["model"] == "qwen-test"

@pytest.mark.asyncio
async def test_gemini_generic_native_400_falls_back_same_model(monkeypatch) -> None:
    provider = GeminiLLMProvider(model="gemini-test", api_key="super-secret")
    fake = SequencedClient(
        [
            ErrorResponse(400, "generic invalid argument from native structured controls"),
            FakeResponse(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {"text": '{"title":"Fallback","sections":["ok"]}'}
                                ]
                            }
                        }
                    ]
                }
            ),
        ]
    )

    async def fake_client():
        return fake

    monkeypatch.setattr(provider, "_get_client", fake_client)
    result = await provider.generate_structured("Create a demo", StructuredDemo)

    assert result.title == "Fallback"
    assert len(fake.calls) == 2
    assert provider.model_name == "gemini-test"


def test_gemini_key_is_not_embedded_in_request_url() -> None:
    provider = GeminiLLMProvider(model="gemini-test", api_key="super-secret")
    url = provider._generate_url()
    assert "super-secret" not in url
    assert "?key=" not in url
    assert url.endswith("models/gemini-test:generateContent")


def test_http_error_redacts_query_credentials() -> None:
    from content_factory.llm.http_utils import LLMHTTPError

    error = LLMHTTPError(
        provider="demo",
        model="demo-model",
        status_code=400,
        body="bad request",
        url="https://example.test/v1/run?key=super-secret&mode=test",
    )
    rendered = str(error)
    assert "super-secret" not in rendered
    assert "%3Credacted%3E" in rendered or "redacted" in rendered
    assert "mode=test" in rendered

@pytest.mark.asyncio
async def test_gemini_429_daily_quota_fails_fast_without_wasteful_retries(monkeypatch) -> None:
    from content_factory.llm.http_utils import LLMQuotaExhaustedError

    provider = GeminiLLMProvider(model="gemini-test", api_key="secret")
    body = (
        '{"error":{"code":429,"status":"RESOURCE_EXHAUSTED",'
        '"message":"Quota exceeded for metric GenerateRequestsPerDayPerProjectPerModel-FreeTier"}}'
    )
    fake = SequencedClient([ErrorResponse(429, body)])

    async def fake_client():
        return fake

    async def no_sleep(_seconds):
        raise AssertionError("daily quota should not sleep/retry")

    monkeypatch.setattr(provider, "_get_client", fake_client)
    monkeypatch.setattr("content_factory.llm.http_utils.asyncio.sleep", no_sleep)
    monkeypatch.setenv("GEMINI_HTTP_RETRIES", "5")
    monkeypatch.setenv("GEMINI_MIN_REQUEST_INTERVAL_SECONDS", "0")

    with pytest.raises(LLMQuotaExhaustedError, match="Quota appears to be exhausted"):
        await provider.generate("hello")

    assert len(fake.calls) == 1
    assert provider.stats()["quota_exhausted"] == 1


@pytest.mark.asyncio
async def test_gemini_429_transient_honors_google_retry_delay(monkeypatch) -> None:
    provider = GeminiLLMProvider(model="gemini-test", api_key="secret")

    class RetryInfoResponse(ErrorResponse):
        def __init__(self):
            payload = {
                "error": {
                    "code": 429,
                    "status": "RESOURCE_EXHAUSTED",
                    "message": "Requests per minute quota exceeded",
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.RetryInfo",
                            "retryDelay": "7s",
                        }
                    ],
                }
            }
            super().__init__(429, json.dumps(payload))
            self._payload = payload
            self.headers = {}

    fake = SequencedClient(
        [
            RetryInfoResponse(),
            FakeResponse({"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}),
        ]
    )
    sleeps = []

    async def fake_client():
        return fake

    async def capture_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(provider, "_get_client", fake_client)
    monkeypatch.setattr("content_factory.llm.http_utils.asyncio.sleep", capture_sleep)
    monkeypatch.setenv("GEMINI_HTTP_RETRIES", "2")
    monkeypatch.setenv("GEMINI_MIN_REQUEST_INTERVAL_SECONDS", "0")

    result = await provider.generate("hello")

    assert result == "ok"
    assert len(fake.calls) == 2
    assert sleeps == [7.0]
    assert provider.stats()["rate_limit_retries"] == 1
