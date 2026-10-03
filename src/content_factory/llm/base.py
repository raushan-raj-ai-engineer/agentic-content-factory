from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

ModelT = TypeVar("ModelT", bound=BaseModel)


class NativeStructuredOutputUnsupported(RuntimeError):
    """Provider/model does not support the requested native structured mode."""


class LLMProvider(ABC):
    """Provider abstraction for language models.

    A primary provider/model is selected before the workflow starts. A wrapper
    may perform a one-way retryable runtime fallback while preserving the same
    provider-neutral contract for every text agent. Structured output is also exposed
    through one provider-neutral contract: adapters may use their native schema
    mechanism, while validation/repair/fallback behavior stays centralized.
    """

    def __init__(self) -> None:
        self._native_structured_disabled = False

    @property
    def provider_name(self) -> str:
        return self.__class__.__name__

    @property
    def model_name(self) -> str:
        return ""

    async def prepare(self) -> None:
        """Validate/resolve the provider before the workflow is locked."""

    async def release(self) -> None:
        """Release provider resources before media generation when useful."""
        close = getattr(self, "aclose", None)
        if callable(close):
            result = close()
            if hasattr(result, "__await__"):
                await result

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> str:
        """Generate a text response."""
        ...

    async def _generate_structured_native(
        self,
        prompt: str,
        response_model: type[ModelT],
        *,
        system_prompt: str | None = None,
    ) -> Any:
        """Provider-specific native schema request.

        Adapters override this when their API exposes schema-constrained output.
        Returning either a decoded object or JSON text is supported. Raising
        NativeStructuredOutputUnsupported permanently switches this provider
        instance to the shared schema-in-prompt fallback for the rest of the run.
        """
        raise NativeStructuredOutputUnsupported(
            f"{self.provider_name} does not expose native structured output."
        )

    async def generate_structured(
        self,
        prompt: str,
        response_model: type[ModelT],
        *,
        system_prompt: str | None = None,
        max_retries: int = 2,
        prefer_native: bool = True,
    ) -> ModelT:
        """Generate one object matching ``response_model``.

        This is deliberately provider-neutral. Each adapter translates the same
        contract into its native API where possible (Ollama schema format,
        Gemini response schema, OpenAI JSON schema, Anthropic tool schema, etc.).
        If a provider/model rejects native schema controls, the run stays on the
        *same locked provider/model* and falls back to schema-in-prompt JSON.
        Validation and repair retries are shared across every provider.
        """
        current_prompt = prompt

        for attempt in range(max_retries + 1):
            raw: Any
            if prefer_native and not getattr(self, "_native_structured_disabled", False):
                try:
                    raw = await self._generate_structured_native(
                        current_prompt,
                        response_model,
                        system_prompt=system_prompt,
                    )
                except NativeStructuredOutputUnsupported as exc:
                    self._native_structured_disabled = True
                    print(
                        f"[LLM STRUCTURED] provider={self.provider_name}, "
                        f"model={self.model_name}: native schema unavailable; "
                        "using same-model schema-in-prompt fallback. "
                        f"Reason: {_safe_preview(exc, 160)}"
                    )
                    raw = await self._generate_structured_prompt_fallback(
                        current_prompt,
                        response_model,
                        system_prompt=system_prompt,
                    )
            else:
                raw = await self._generate_structured_prompt_fallback(
                    current_prompt,
                    response_model,
                    system_prompt=system_prompt,
                )

            try:
                return _validate_structured_payload(raw, response_model)
            except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as exc:
                if attempt >= max_retries:
                    preview = _safe_preview(raw)
                    raise ValueError(
                        f"{self.provider_name} failed to produce valid structured "
                        f"output after {max_retries + 1} attempts. "
                        f"Response preview: {preview!r}"
                    ) from exc

                current_prompt = self._build_repair_prompt(
                    prompt=prompt,
                    response=_stringify_for_repair(raw),
                    error=str(exc),
                    response_model=response_model,
                )

        raise RuntimeError("Unreachable LLM structured-output state.")

    async def _generate_structured_prompt_fallback(
        self,
        prompt: str,
        response_model: type[ModelT],
        *,
        system_prompt: str | None,
    ) -> str:
        schema = response_model.model_json_schema()
        schema_prompt = f"""
{prompt}

Return exactly one JSON value matching this JSON Schema:
{json.dumps(schema, ensure_ascii=False)}

Output rules:
- JSON only.
- No markdown fences.
- No explanation before or after the JSON.
- Do not add fields that are not in the schema.
""".strip()
        return await self.generate(schema_prompt, system_prompt=system_prompt)

    @staticmethod
    def _build_repair_prompt(
        *,
        prompt: str,
        response: str,
        error: str,
        response_model: type[ModelT],
    ) -> str:
        schema = response_model.model_json_schema()
        return f"""
Your previous response was invalid.

Original task:
{prompt}

Your previous response:
{response}

Validation error:
{error}

Required JSON schema:
{json.dumps(schema, indent=2, ensure_ascii=False)}

Return ONLY one valid JSON object matching this schema.
Do not use markdown.
Do not add explanations.
Do not add extra fields.
Do not wrap the object inside another object.
""".strip()


def _validate_structured_payload(
    raw: Any,
    response_model: type[ModelT],
) -> ModelT:
    if isinstance(raw, response_model):
        return raw
    if isinstance(raw, BaseModel):
        return response_model.model_validate(raw.model_dump())
    if isinstance(raw, str):
        raw = _decode_json_payload(raw)
    return response_model.model_validate(raw)


def _stringify_for_repair(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


def _safe_preview(value: Any, limit: int = 220) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _strip_markdown_fence(text: str) -> str:
    stripped = text.strip()
    match = re.fullmatch(
        r"```(?:json|JSON)?\s*(.*?)\s*```",
        stripped,
        flags=re.DOTALL,
    )
    return match.group(1).strip() if match else stripped


def _decode_json_payload(response: str) -> Any:
    """Decode a model response containing one JSON value.

    Accepts plain JSON, fenced JSON, or a short explanatory prefix/suffix around
    a JSON object. Native schema modes remain preferred, but this parser gives
    every provider the same compatibility safety net.
    """
    text = _strip_markdown_fence(str(response or ""))
    if not text:
        raise ValueError("LLM returned an empty response.")

    try:
        return json.loads(text)
    except json.JSONDecodeError as direct_error:
        decoder = json.JSONDecoder()
        starts = [index for index, char in enumerate(text) if char in "[{"]
        for start in starts:
            try:
                payload, end = decoder.raw_decode(text[start:])
            except json.JSONDecodeError:
                continue
            trailing = text[start + end :].strip()
            if not trailing or trailing.startswith("```"):
                return payload
        raise direct_error
