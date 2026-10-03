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


class AnthropicLLMProvider(LLMProvider):
    """Anthropic Messages API provider using one locked model per run."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str = "https://api.anthropic.com/v1",
        timeout: float = 180.0,
        max_tokens: int = 8192,
    ) -> None:
        self._model = str(model or "").strip()
        self._api_key = str(api_key or "").strip()
        self._base_url = base_url.rstrip("/")
        self._timeout = max(30.0, min(300.0, float(timeout)))
        self._max_tokens = max(1024, int(max_tokens))
        self._client: httpx.AsyncClient | None = None
        self._stats: dict[str, Any] = {
            "requests": 0,
            "transient_retries": 0,
            "structured_requests": 0,
        }

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def model_name(self) -> str:
        return self._model

    async def prepare(self) -> None:
        if not self._api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required for the Anthropic provider.")
        if not self._model:
            raise RuntimeError("ANTHROPIC_MODEL is required for the Anthropic provider.")

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> str:
        await self.prepare()
        payload = self._base_payload(prompt, system_prompt=system_prompt)
        data = await self._post("/messages", payload)
        return self._extract_text(data)

    async def _generate_structured_native(
        self,
        prompt: str,
        response_model: type[ModelT],
        *,
        system_prompt: str | None = None,
    ) -> dict[str, Any] | str:
        """Use a forced schema tool as Anthropic's structured-output adapter.

        Tool input is JSON-schema constrained and returned as a decoded object.
        If a model/endpoint rejects this mechanism, the shared base class keeps
        the same Claude model and uses schema-in-prompt JSON instead.
        """
        await self.prepare()
        payload = self._base_payload(prompt, system_prompt=system_prompt)
        payload["tools"] = [
            {
                "name": "emit_structured_response",
                "description": "Return the final structured response for this task.",
                "input_schema": response_model.model_json_schema(),
            }
        ]
        payload["tool_choice"] = {
            "type": "tool",
            "name": "emit_structured_response",
        }
        try:
            data = await self._post("/messages", payload)
        except LLMHTTPError as exc:
            if _is_structured_capability_error(exc):
                raise NativeStructuredOutputUnsupported(
                    f"Anthropic model {self._model!r} rejected schema tool output "
                    f"(HTTP {exc.status_code})."
                ) from exc
            raise

        self._stats["structured_requests"] += 1
        content = data.get("content")
        if not isinstance(content, list):
            raise RuntimeError("Anthropic returned no content list.")
        for item in content:
            if not isinstance(item, dict):
                continue
            if (
                item.get("type") == "tool_use"
                and item.get("name") == "emit_structured_response"
            ):
                value = item.get("input")
                if isinstance(value, dict):
                    return value
        # Some compatible/older Claude endpoints may still answer with JSON text.
        return self._extract_text(data)

    def _base_payload(
        self,
        prompt: str,
        *,
        system_prompt: str | None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            payload["system"] = system_prompt
        return payload

    @staticmethod
    def _extract_text(data: dict[str, object]) -> str:
        content = data.get("content")
        if not isinstance(content, list):
            raise RuntimeError("Anthropic returned no content list.")
        texts = [
            str(item["text"])
            for item in content
            if isinstance(item, dict)
            and item.get("type") == "text"
            and isinstance(item.get("text"), str)
        ]
        if not texts:
            raise RuntimeError("Anthropic returned no text response.")
        return "\n".join(texts)

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
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                },
                limits=httpx.Limits(max_keepalive_connections=4, max_connections=8),
            )
        return self._client

    async def _post(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        url = f"{self._base_url}{path}"
        client = await self._get_client()
        return await post_json_with_retries(
            client=client,
            url=url,
            payload=payload,
            provider=self.provider_name,
            model=self._model,
            timeout_seconds=self._timeout,
            stats=self._stats,
            retry_env_names=("ANTHROPIC_HTTP_RETRIES",),
        )


def _is_structured_capability_error(exc: LLMHTTPError) -> bool:
    if exc.status_code not in {400, 404, 415, 422}:
        return False
    body = exc.body.casefold()
    markers = (
        "tool_choice",
        "input_schema",
        "tools",
        "structured output",
        "unknown field",
        "unsupported",
    )
    return any(marker in body for marker in markers)
