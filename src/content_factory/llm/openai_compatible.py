from __future__ import annotations

from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from content_factory.llm.base import (
    LLMProvider,
    NativeStructuredOutputUnsupported,
)
from content_factory.llm.http_utils import LLMHTTPError, post_json_with_retries

ModelT = TypeVar("ModelT", bound=BaseModel)


class OpenAICompatibleLLMProvider(LLMProvider):
    """Provider for OpenAI-style ``/chat/completions`` APIs.

    OpenAI and third-party compatible endpoints share this adapter. A model that
    supports JSON Schema gets native structured output; endpoints that reject
    ``response_format`` automatically keep the same model and use the shared
    schema-in-prompt fallback.
    """

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str = "",
        timeout: float = 180.0,
        provider_name: str = "compatible",
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self._model = str(model or "").strip()
        self._base_url = base_url.rstrip("/")
        self._api_key = str(api_key or "").strip()
        self._timeout = max(30.0, min(300.0, float(timeout)))
        self._provider_name = provider_name
        self._extra_headers = dict(extra_headers or {})
        self._client: httpx.AsyncClient | None = None
        self._stats: dict[str, Any] = {
            "requests": 0,
            "transient_retries": 0,
            "structured_requests": 0,
        }

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model

    async def prepare(self) -> None:
        if not self._base_url:
            raise RuntimeError(f"{self._provider_name} base URL is not configured.")
        if not self._model:
            raise RuntimeError(f"{self._provider_name} model is not configured.")
        if self._provider_name == "openai" and not self._api_key:
            raise RuntimeError("OPENAI_API_KEY is required for the OpenAI provider.")

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> str:
        await self.prepare()
        payload = self._base_payload(prompt, system_prompt=system_prompt)
        data = await self._post("/chat/completions", payload)
        return self._extract_content(data)

    async def _generate_structured_native(
        self,
        prompt: str,
        response_model: type[ModelT],
        *,
        system_prompt: str | None = None,
    ) -> str:
        await self.prepare()
        payload = self._base_payload(prompt, system_prompt=system_prompt)
        payload["temperature"] = 0.1
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "structured_response",
                "schema": response_model.model_json_schema(),
            },
        }
        try:
            data = await self._post("/chat/completions", payload)
        except LLMHTTPError as exc:
            if _is_structured_capability_error(exc):
                raise NativeStructuredOutputUnsupported(
                    f"{self.provider_name} model {self._model!r} rejected "
                    f"JSON-schema response_format (HTTP {exc.status_code})."
                ) from exc
            raise
        self._stats["structured_requests"] += 1
        return self._extract_content(data)

    def _base_payload(
        self,
        prompt: str,
        *,
        system_prompt: str | None,
    ) -> dict[str, object]:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return {
            "model": self._model,
            "messages": messages,
            "temperature": 0.2,
        }

    def _extract_content(self, data: dict[str, object]) -> str:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError(
                f"{self._provider_name} returned no choices for model {self._model!r}."
            )
        first = choices[0]
        if not isinstance(first, dict):
            raise RuntimeError(f"{self._provider_name} returned an invalid choice object.")
        message = first.get("message")
        if not isinstance(message, dict):
            raise RuntimeError(f"{self._provider_name} returned no message object.")
        refusal = message.get("refusal")
        if isinstance(refusal, str) and refusal.strip():
            raise RuntimeError(f"{self._provider_name} refused the request: {refusal}")
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(str(item["text"]))
            if parts:
                return "\n".join(parts)
        raise RuntimeError(
            f"{self._provider_name} returned an invalid text response for {self._model!r}."
        )

    async def release(self) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def stats(self) -> dict[str, Any]:
        return dict(self._stats)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"Content-Type": "application/json", **self._extra_headers}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers=headers,
                limits=httpx.Limits(max_keepalive_connections=4, max_connections=8),
            )
        return self._client

    async def _post(
        self,
        path: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        url = f"{self._base_url}{path}"
        client = await self._get_client()
        provider_env = (
            "OPENAI_HTTP_RETRIES" if self._provider_name == "openai"
            else "LLM_COMPATIBLE_HTTP_RETRIES"
        )
        return await post_json_with_retries(
            client=client,
            url=url,
            payload=payload,
            provider=self._provider_name,
            model=self._model,
            timeout_seconds=self._timeout,
            stats=self._stats,
            retry_env_names=(provider_env,),
        )


class OpenAILLMProvider(OpenAICompatibleLLMProvider):
    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 180.0,
    ) -> None:
        super().__init__(
            model=model,
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            provider_name="openai",
        )


def _is_structured_capability_error(exc: LLMHTTPError) -> bool:
    if exc.status_code not in {400, 404, 415, 422}:
        return False
    body = exc.body.casefold()
    markers = (
        "response_format",
        "json_schema",
        "structured output",
        "unsupported parameter",
        "unknown parameter",
    )
    return any(marker in body for marker in markers)
