from __future__ import annotations

import os
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

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
        self._requested_model = str(model or "auto").strip() or "auto"
        self._model = self._requested_model
        self._model_checked = False
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

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model

    async def prepare(self) -> None:
        await self._ensure_model_available()

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> str:
        await self._ensure_model_available()
        payload: dict[str, object] = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "think": False,
            # Keep text model resident during the text/reasoning phase.
            "keep_alive": "30m",
            "options": {"num_predict": _ollama_num_predict()},
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

    async def _generate_structured_native(
        self,
        prompt: str,
        response_model: type[ModelT],
        *,
        system_prompt: str | None = None,
    ) -> str:
        """Use Ollama's JSON-schema ``format`` capability."""
        await self._ensure_model_available()
        payload: dict[str, object] = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "format": response_model.model_json_schema(),
            "options": {
                "temperature": 0.2,
                "num_predict": _ollama_structured_num_predict(response_model),
            },
            "keep_alive": "30m",
        }
        if system_prompt is not None:
            payload["system"] = system_prompt

        data = await self._post_generate(payload)
        response_text = data.get("response")
        if not isinstance(response_text, str):
            raise RuntimeError(
                "Ollama returned an invalid structured response: "
                "missing string 'response'."
            )
        return response_text

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

    async def switch_to_alternate_model(self, reason: str = "runtime timeout") -> bool:
        """Switch to another installed local model for the rest of the run.

        This is deliberately one-way. It is used after a bounded workflow-level
        timeout so a slow local model cannot repeatedly stall later agents.
        """
        names = await self._installed_models()
        current = self._model
        candidates = [name for name in names if name.casefold() != current.casefold()]
        if not candidates:
            return False

        raw_order = os.getenv(
            "CONTENT_FACTORY_OLLAMA_FAILOVER_ORDER",
            "llama3.2,qwen2.5:3b,qwen3:4b,qwen,llama",
        )
        prefixes = [item.strip() for item in raw_order.split(",") if item.strip()]
        selected: str | None = None
        for prefix in prefixes:
            selected = next(
                (name for name in candidates if name.casefold().startswith(prefix.casefold())),
                None,
            )
            if selected:
                break
        selected = selected or candidates[0]

        # Avoid keeping two multi-GB models resident on small-memory Macs.
        try:
            client = await self._get_client()
            await client.post(
                f"{self._base_url}/api/generate",
                json={"model": current, "stream": False, "keep_alive": 0},
                timeout=12.0,
            )
        except Exception:
            pass

        self._model = selected
        self._model_checked = True
        self._native_structured_disabled = False
        print(
            "[LLM LOCAL FAILOVER] "
            f"from={current}, to={selected}; reason={reason}"
        )
        return True

    async def _installed_models(self) -> list[str]:
        client = await self._get_client()
        url = f"{self._base_url}/api/tags"
        try:
            response = await client.get(url)
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"Ollama model discovery timed out while calling {url}."
            ) from exc
        except httpx.RequestError as exc:
            detail = str(exc) or exc.__class__.__name__
            raise RuntimeError(
                f"Unable to reach local Ollama at {url}: {detail}. "
                "Start it with `ollama serve` or open the Ollama app."
            ) from exc

        if response.is_error:
            raise RuntimeError(
                f"Ollama model discovery failed: HTTP {response.status_code} "
                f"from {url}: {response.text[:1000]}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("Ollama /api/tags returned non-JSON data.") from exc

        names = [
            str(item.get("name") or "").strip()
            for item in (payload.get("models", []) if isinstance(payload, dict) else [])
            if isinstance(item, dict)
        ]
        names = [name for name in names if name]
        if not names:
            raise RuntimeError(
                "Ollama is running, but no local models are installed. "
                "Install one first, for example: `ollama pull qwen2.5:3b`."
            )
        return names

    async def _ensure_model_available(self) -> None:
        """Resolve the configured Ollama model against models installed locally.

        ``model: auto`` chooses a small local teaching-capable model. If a
        configured model has been removed, the provider falls back to another
        installed Qwen/Llama model instead of failing halfway through a run.
        Set CONTENT_FACTORY_STRICT_LLM_MODEL=1 to require the exact model name.
        """
        if self._model_checked:
            return

        names = await self._installed_models()

        requested = self._requested_model
        selected: str | None = None
        if requested.casefold() != "auto":
            selected = next((name for name in names if name == requested), None)
            selected = selected or next(
                (name for name in names if name.casefold() == requested.casefold()),
                None,
            )

        if selected is None:
            strict = os.getenv("CONTENT_FACTORY_STRICT_LLM_MODEL", "0").strip().lower() in {
                "1", "true", "yes", "on"
            }
            if strict and requested.casefold() != "auto":
                raise RuntimeError(
                    f"Configured Ollama model {requested!r} is not installed. "
                    f"Installed models: {', '.join(names)}"
                )

            preferred_prefixes = (
                "qwen2.5:3b",
                "qwen3:4b",
                "qwen",
                "llama3.2",
                "llama",
            )
            for prefix in preferred_prefixes:
                selected = next(
                    (name for name in names if name.casefold().startswith(prefix.casefold())),
                    None,
                )
                if selected:
                    break
            selected = selected or names[0]

        previous = self._model
        self._model = selected
        self._model_checked = True

        if requested.casefold() == "auto":
            print(f"[LLM] Auto-selected installed Ollama model: {selected}")
        elif selected != requested:
            print(
                f"[LLM] Configured model {requested!r} is not installed; "
                f"using installed model {selected!r} instead."
            )
        elif previous == requested:
            print(f"[LLM] Ollama model ready: {selected}")

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


def _ollama_num_predict() -> int:
    raw = os.getenv("CONTENT_FACTORY_OLLAMA_NUM_PREDICT", "2400")
    try:
        value = int(raw)
    except ValueError:
        value = 2400
    return max(256, min(4096, value))


def _ollama_structured_num_predict(response_model: type[BaseModel]) -> int:
    # Script chunks are intentionally small in V23; bounding their token budget
    # prevents a local model from wandering for minutes inside JSON generation.
    base = _ollama_num_predict()
    if response_model.__name__ in {"_ScriptChunk", "_MicroSection"}:
        return min(base, 1100)
    return base
