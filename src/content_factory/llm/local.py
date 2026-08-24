from __future__ import annotations

import json
from typing import TypeVar, Any

import httpx
from pydantic import BaseModel, ValidationError

from content_factory.llm.base import LLMProvider

ModelT = TypeVar("ModelT", bound=BaseModel)


class LocalLLMProvider(LLMProvider):
    """
    Local Ollama provider optimized for a multi-agent text phase.

    - reuses one HTTP connection pool
    - keeps the model warm across text agents
    - can explicitly unload it before voice/visual generation
    """

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        timeout: float = 600.0,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        # V21: local text calls must never hang for ten minutes on 8GB Apple Silicon.
        self._timeout = max(30.0, min(180.0, float(timeout)))
        self._client: httpx.AsyncClient | None = None
        self._stats = {
            "requests": 0,
            "ollama_load_seconds": 0.0,
            "ollama_eval_seconds": 0.0,
            "prompt_eval_seconds": 0.0,
        }

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> str:
        payload: dict[str, object] = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "think": False,
            # Keep text model resident during the text/reasoning phase.
            "keep_alive": "30m",
        }

        if system_prompt is not None:
            payload["system"] = system_prompt

        data = await self._post_generate(payload)
        response_text = data.get("response")

        if not isinstance(response_text, str):
            raise RuntimeError(
                "Ollama returned an invalid response: "
                "missing string 'response'."
            )

        return response_text

    async def generate_structured(
        self,
        prompt: str,
        response_model: type[ModelT],
        *,
        system_prompt: str | None = None,
        max_retries: int = 2,
    ) -> ModelT:
        schema = response_model.model_json_schema()
        current_prompt = prompt

        for attempt in range(
            max_retries + 1
        ):
            payload: dict[str, object] = {
                "model": self._model,
                "prompt": current_prompt,
                "stream": False,
                "think": False,
                "format": schema,
                "options": {
                    "temperature": 0.2,
                },
                "keep_alive": "30m",
            }

            if system_prompt is not None:
                payload["system"] = system_prompt

            data = await self._post_generate(payload)
            response_text = data.get(
                "response"
            )

            if not isinstance(
                response_text,
                str,
            ):
                raise RuntimeError(
                    "Ollama returned an invalid structured response: "
                    "missing string 'response'."
                )

            try:
                parsed = json.loads(
                    response_text
                )
                return response_model.model_validate(
                    parsed
                )
            except (
                json.JSONDecodeError,
                ValidationError,
            ) as exc:
                if attempt >= max_retries:
                    raise ValueError(
                        "Ollama failed to produce valid structured output "
                        f"after {max_retries + 1} attempts. "
                        f"Last response: {response_text[:1000]}"
                    ) from exc

                current_prompt = self._build_repair_prompt(
                    prompt=prompt,
                    response=response_text,
                    error=str(exc),
                    response_model=response_model,
                )

        raise RuntimeError(
            "Unreachable Ollama execution state."
        )

    async def release(self) -> None:
        """Unload the Ollama model before MPS-heavy media generation."""
        url = f"{self._base_url}/api/generate"

        try:
            client = await self._get_client()
            response = await client.post(
                url,
                json={
                    "model": self._model,
                    "stream": False,
                    "keep_alive": 0,
                },
            )

            if response.is_error:
                print(
                    f"[RESOURCE] Ollama unload returned HTTP "
                    f"{response.status_code}; continuing."
                )
            else:
                print(
                    f"[RESOURCE] Ollama model unloaded: {self._model}"
                )
        except Exception as exc:
            print(
                "[RESOURCE] Ollama unload skipped: "
                f"{exc.__class__.__name__}"
            )
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def stats(self) -> dict[str, Any]:
        return dict(
            self._stats
        )

    async def _get_client(
        self,
    ) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                trust_env=False,
                limits=httpx.Limits(
                    max_keepalive_connections=4,
                    max_connections=8,
                ),
            )

        return self._client

    async def _post_generate(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        url = f"{self._base_url}/api/generate"

        try:
            client = await self._get_client()
            response = await client.post(
                url,
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"Ollama timed out after {self._timeout} seconds "
                f"({exc.__class__.__name__}) while calling {url}. "
                f"Model: {self._model}"
            ) from exc
        except httpx.RequestError as exc:
            detail = str(exc) or exc.__class__.__name__
            raise RuntimeError(
                f"Unable to reach local Ollama at {url}: {detail}. "
                f"Model: {self._model}"
            ) from exc

        if response.is_error:
            raise RuntimeError(
                f"Ollama request failed: HTTP {response.status_code}\n"
                f"URL: {url}\n"
                f"Model: {self._model}\n"
                f"Response: {response.text[:2000]}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(
                "Ollama returned a non-JSON HTTP response: "
                f"{response.text[:1000]}"
            ) from exc

        if not isinstance(
            data,
            dict,
        ):
            raise RuntimeError(
                "Ollama returned an unexpected JSON response type."
            )

        self._stats["requests"] += 1
        self._stats["ollama_load_seconds"] += (
            float(
                data.get(
                    "load_duration",
                    0,
                )
                or 0
            )
            / 1_000_000_000
        )
        self._stats["ollama_eval_seconds"] += (
            float(
                data.get(
                    "eval_duration",
                    0,
                )
                or 0
            )
            / 1_000_000_000
        )
        self._stats["prompt_eval_seconds"] += (
            float(
                data.get(
                    "prompt_eval_duration",
                    0,
                )
                or 0
            )
            / 1_000_000_000
        )

        return data

    @staticmethod
    def _build_repair_prompt(
        *,
        prompt: str,
        response: str,
        error: str,
        response_model: type[ModelT],
    ) -> str:
        return f"""
The previous response failed JSON/schema validation.

ORIGINAL TASK
{prompt}

FAILED RESPONSE
{response}

VALIDATION ERROR
{error}

Return ONLY valid JSON matching this schema:
{json.dumps(response_model.model_json_schema(), indent=2)}
"""
