from __future__ import annotations

import asyncio
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from content_factory.llm.base import LLMProvider
from content_factory.llm.http_utils import LLMHTTPError, LLMQuotaExhaustedError

ModelT = TypeVar("ModelT", bound=BaseModel)

_RETRYABLE_HTTP = {408, 409, 425, 429, 500, 502, 503, 504}


class RuntimeFailoverLLMProvider(LLMProvider):
    """Keep one primary provider until a retryable runtime failure occurs.

    The fallback is prepared lazily. Once activated, every later request in the
    workflow stays on the fallback provider/model so the run does not bounce
    between providers.
    """

    def __init__(self, primary: LLMProvider, fallback: LLMProvider) -> None:
        super().__init__()
        self._primary = primary
        self._fallback = fallback
        self._active = primary
        self._switch_lock = asyncio.Lock()
        self._primary_released = False

    @property
    def provider_name(self) -> str:
        return self._active.provider_name

    @property
    def model_name(self) -> str:
        return self._active.model_name

    @property
    def using_fallback(self) -> bool:
        return self._active is self._fallback

    async def prepare(self) -> None:
        await self._primary.prepare()

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> str:
        async def call(provider: LLMProvider) -> str:
            return await provider.generate(prompt, system_prompt=system_prompt)

        return await self._call_with_failover(call)

    async def generate_structured(
        self,
        prompt: str,
        response_model: type[ModelT],
        *,
        system_prompt: str | None = None,
        max_retries: int = 2,
        prefer_native: bool = True,
    ) -> ModelT:
        async def call(provider: LLMProvider) -> ModelT:
            return await provider.generate_structured(
                prompt,
                response_model,
                system_prompt=system_prompt,
                max_retries=max_retries,
                prefer_native=prefer_native,
            )

        return await self._call_with_failover(call)

    async def force_fallback(self, reason: str) -> bool:
        """Switch to fallback after an outer workflow timeout.

        This is used when a caller-level ``asyncio.wait_for`` fires before the
        provider can surface its own timeout exception.
        """
        if self.using_fallback:
            return False
        async with self._switch_lock:
            if self.using_fallback:
                return False
            await self._activate_fallback(reason)
            return True

    async def retry_primary(self, reason: str = "stage boundary retry") -> bool:
        """Re-arm the primary provider for a later quality-critical stage.

        Runtime fallback remains available. This is intentionally stage-scoped:
        a transient timeout during script generation should not force the visual
        director/reviewer to use a weaker local model for the rest of the run.
        """
        if not self.using_fallback:
            return True
        async with self._switch_lock:
            if not self.using_fallback:
                return True
            try:
                await self._primary.prepare()
            except Exception as exc:
                print(
                    "[LLM PRIMARY RETRY] unavailable; staying on fallback: "
                    f"{exc.__class__.__name__}: {str(exc)[:160]}"
                )
                return False
            self._active = self._primary
            self._primary_released = False
            print(
                "[LLM PRIMARY RETRY] "
                f"restored={self._primary.provider_name}:{self._primary.model_name}; "
                f"reason={reason}"
            )
            return True

    async def switch_to_alternate_model(self, reason: str = "runtime timeout") -> bool:
        if not self.using_fallback:
            return await self.force_fallback(reason)
        switch = getattr(self._fallback, "switch_to_alternate_model", None)
        if callable(switch):
            return bool(await switch(reason))
        return False

    async def _call_with_failover(self, call: Any) -> Any:
        provider = self._active
        try:
            return await call(provider)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if provider is self._fallback or not _is_retryable_runtime_failure(exc):
                raise

            async with self._switch_lock:
                if self._active is self._primary:
                    await self._activate_fallback(_reason(exc))
                provider = self._active

            return await call(provider)

    async def _activate_fallback(self, reason: str) -> None:
        try:
            await self._fallback.prepare()
        except Exception as fallback_exc:
            raise RuntimeError(
                "Runtime LLM fallback was required but Ollama could not start: "
                f"{fallback_exc}"
            ) from fallback_exc

        print(
            "[LLM RUNTIME FALLBACK] "
            f"from={self._primary.provider_name}:{self._primary.model_name}, "
            f"to={self._fallback.provider_name}:{self._fallback.model_name}; "
            f"reason={reason}"
        )
        self._active = self._fallback
        if not self._primary_released:
            try:
                await self._primary.release()
            finally:
                self._primary_released = True

    async def release(self) -> None:
        seen: set[int] = set()
        for provider in (self._active, self._primary, self._fallback):
            ident = id(provider)
            if ident in seen:
                continue
            seen.add(ident)
            try:
                await provider.release()
            except Exception:
                pass

    def stats(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "active_provider": self.provider_name,
            "active_model": self.model_name,
            "runtime_fallback": self.using_fallback,
        }
        for label, provider in (("primary", self._primary), ("fallback", self._fallback)):
            stats_fn = getattr(provider, "stats", None)
            if callable(stats_fn):
                try:
                    result[label] = stats_fn()
                except Exception:
                    pass
        return result


def _is_retryable_runtime_failure(exc: Exception) -> bool:
    if isinstance(exc, LLMQuotaExhaustedError):
        return True
    if isinstance(exc, LLMHTTPError):
        return exc.status_code in _RETRYABLE_HTTP
    if isinstance(exc, (httpx.TimeoutException, httpx.RequestError, TimeoutError)):
        return True

    text = str(exc).casefold()
    markers = (
        "timed out",
        "timeout",
        "unable to reach",
        "connection reset",
        "connection refused",
        "connection error",
        "temporarily unavailable",
        "rate limit",
        "resource_exhausted",
        "quota",
        "http 429",
        "http 500",
        "http 502",
        "http 503",
        "http 504",
    )
    return isinstance(exc, RuntimeError) and any(marker in text for marker in markers)


def _reason(exc: Exception) -> str:
    text = str(exc).replace("\n", " ").strip()
    if len(text) > 220:
        text = text[:217] + "..."
    return f"{exc.__class__.__name__}: {text}" if text else exc.__class__.__name__
