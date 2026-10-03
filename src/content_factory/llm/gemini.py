from __future__ import annotations

import asyncio
import os
import time
from typing import Any, TypeVar
from urllib.parse import quote

import httpx
from pydantic import BaseModel

from content_factory.llm.base import (
    LLMProvider,
    NativeStructuredOutputUnsupported,
    _safe_preview,
)
from content_factory.llm.http_utils import LLMHTTPError, post_json_with_retries

ModelT = TypeVar("ModelT", bound=BaseModel)


class GeminiLLMProvider(LLMProvider):
    """Google Gemini REST provider using one locked model for the whole run."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout: float = 180.0,
    ) -> None:
        self._model = str(model or "").strip()
        self._api_key = str(api_key or "").strip()
        self._base_url = base_url.rstrip("/")
        self._timeout = max(30.0, min(300.0, float(timeout)))
        self._client: httpx.AsyncClient | None = None
        self._stats: dict[str, Any] = {
            "requests": 0,
            "transient_retries": 0,
            "structured_requests": 0,
            "rate_limit_retries": 0,
            "quota_exhausted": 0,
        }
        self._request_lock = asyncio.Lock()
        self._last_request_started = 0.0

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model

    async def prepare(self) -> None:
        if not self._api_key:
            raise RuntimeError("GEMINI_API_KEY is required for the Gemini provider.")
        if not self._model:
            raise RuntimeError("GEMINI_MODEL is required for the Gemini provider.")

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> str:
        await self.prepare()
        payload = self._base_payload(prompt, system_prompt=system_prompt)
        data = await self._post(self._generate_url(), payload)
        return self._extract_text(data)

    async def _generate_structured_native(
        self,
        prompt: str,
        response_model: type[ModelT],
        *,
        system_prompt: str | None = None,
    ) -> str:
        """Use generateContent's broadly compatible JSON-schema controls.

        ``responseMimeType`` + ``responseJsonSchema`` work across more Gemini
        generateContent model generations than the newer ``responseFormat``
        shape. If a model rejects native structured controls, the shared base
        layer keeps this same Gemini model and falls back to schema-in-prompt.
        """
        await self.prepare()
        payload = self._base_payload(prompt, system_prompt=system_prompt)
        generation = payload["generationConfig"]
        assert isinstance(generation, dict)
        generation["responseMimeType"] = "application/json"
        generation["responseJsonSchema"] = response_model.model_json_schema()
        generation["temperature"] = 0.1

        try:
            data = await self._post(self._generate_url(), payload)
        except LLMHTTPError as exc:
            if _is_structured_capability_error(exc):
                raise NativeStructuredOutputUnsupported(
                    f"Gemini model {self._model!r} rejected native JSON schema "
                    f"controls (HTTP {exc.status_code})."
                ) from exc
            raise

        self._stats["structured_requests"] += 1
        return self._extract_text(data)

    def _base_payload(
        self,
        prompt: str,
        *,
        system_prompt: str | None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2},
        }
        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}
        return payload

    def _generate_url(self) -> str:
        model = quote(self._model, safe="-_.:")
        # Keep credentials out of URLs so exceptions, proxies, shell history,
        # and logs cannot accidentally expose the Gemini key.
        return f"{self._base_url}/models/{model}:generateContent"

    @staticmethod
    def _extract_text(data: dict[str, object]) -> str:
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            prompt_feedback = data.get("promptFeedback")
            raise RuntimeError(
                "Gemini returned no candidates. "
                f"Prompt feedback: {_safe_preview(prompt_feedback)}"
            )
        first = candidates[0]
        if not isinstance(first, dict):
            raise RuntimeError("Gemini returned an invalid candidate object.")
        finish_reason = str(first.get("finishReason") or "").strip()
        content = first.get("content")
        if not isinstance(content, dict):
            raise RuntimeError(
                "Gemini returned no content object. "
                f"finishReason={finish_reason or 'unknown'}"
            )
        parts = content.get("parts")
        if not isinstance(parts, list):
            raise RuntimeError(
                "Gemini returned no content parts. "
                f"finishReason={finish_reason or 'unknown'}"
            )
        texts = [
            str(item["text"])
            for item in parts
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ]
        if not texts:
            raise RuntimeError(
                "Gemini returned no text response. "
                f"finishReason={finish_reason or 'unknown'}"
            )
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
                    "x-goog-api-key": self._api_key,
                },
                limits=httpx.Limits(max_keepalive_connections=4, max_connections=8),
            )
        return self._client

    async def _post(self, url: str, payload: dict[str, object]) -> dict[str, object]:
        # Smooth bursts from many sequential text agents. This is intentionally
        # same-provider/model pacing, never a hidden provider fallback.
        async with self._request_lock:
            min_interval = _gemini_min_request_interval_seconds()
            elapsed = time.monotonic() - self._last_request_started
            if self._last_request_started and elapsed < min_interval:
                wait = min_interval - elapsed
                print(f"[GEMINI PACE] waiting {wait:.1f}s before next locked-model request")
                await asyncio.sleep(wait)
            self._last_request_started = time.monotonic()
            client = await self._get_client()
            return await post_json_with_retries(
                client=client,
                url=url,
                payload=payload,
                provider=self.provider_name,
                model=self._model,
                timeout_seconds=self._timeout,
                stats=self._stats,
                retry_env_names=("GEMINI_HTTP_RETRIES",),
            )


def _gemini_min_request_interval_seconds() -> float:
    raw = os.getenv("GEMINI_MIN_REQUEST_INTERVAL_SECONDS", "2.0")
    try:
        value = float(raw)
    except ValueError:
        value = 2.0
    return max(0.0, min(30.0, value))


def _is_structured_capability_error(exc: LLMHTTPError) -> bool:
    # This helper is called only around a request that adds native structured-
    # output controls. Gemini model generations expose different schema subsets,
    # and unsupported combinations are reported with several different 4xx
    # bodies. Treat validation-style 4xx responses as a capability miss and retry
    # the SAME locked model through the shared schema-in-prompt path. If the
    # underlying prompt/model is itself invalid, that fallback request will fail
    # normally and surface the real error.
    return exc.status_code in {400, 404, 422}
