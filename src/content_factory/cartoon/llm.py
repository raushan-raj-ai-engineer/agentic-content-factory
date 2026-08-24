from __future__ import annotations

import json
import os
from typing import TypeVar

import httpx

from pydantic import BaseModel, ValidationError

from content_factory.llm.local import LocalLLMProvider

ModelT = TypeVar(
    "ModelT",
    bound=BaseModel,
)


class CartoonLLMProvider(LocalLLMProvider):
    """
    Cartoon-only Ollama tuning.

    Keeps qwen3:8b and structured generation, while bounding context,
    generated tokens and CPU helper threads. The global factual LLM provider
    is not modified.
    """


    async def fast_preflight(self) -> bool:
        """V17.3 fail-fast Ollama readiness probe.

        This intentionally avoids the large cartoon schema. A local model that
        cannot answer this tiny request promptly should not be allowed to burn
        600s repeatedly during story planning.
        """
        timeout = max(15.0, min(90.0, float(os.getenv("CONTENT_FACTORY_CARTOON_PREFLIGHT_TIMEOUT", "30"))))
        fast_model = os.getenv("CONTENT_FACTORY_CARTOON_FAST_MODEL", self._model).strip() or self._model
        payload: dict[str, object] = {
            "model": fast_model,
            "prompt": 'Return exactly: {"ok":1}',
            "stream": False,
            "think": False,
            "format": "json",
            "options": {
                "temperature": 0.0,
                "num_ctx": 512,
                "num_predict": 24,
                "num_thread": max(2, min(8, int(os.getenv("CONTENT_FACTORY_CARTOON_NUM_THREAD", "4")))),
            },
            "keep_alive": "15m",
        }
        try:
            data = await self._post_generate_with_timeout(payload, timeout=timeout)
            text = data.get("response")
            if not isinstance(text, str):
                return False
            parsed = json.loads(text)
            return isinstance(parsed, dict) and int(parsed.get("ok", 0)) == 1
        except Exception as exc:
            print(
                "[CARTOON LLM V17.3] "
                f"preflight=FAIL; error={type(exc).__name__}; reason={str(exc)[:160]!r}"
            )
            return False

    async def generate_fast_structured(
        self,
        prompt: str,
        response_model: type[ModelT],
        *,
        system_prompt: str | None = None,
        rescue: bool = False,
    ) -> ModelT:
        """Generate compact creative JSON with a bounded timeout.

        Unlike generate_structured(), this uses Ollama's lightweight JSON mode
        instead of feeding the complete Pydantic production schema into the
        constrained decoder. The caller uses a deliberately small creative
        response model and deterministic code fills camera/pose/SFX fields.
        """
        timeout_default = "45" if rescue else "120"
        timeout = max(30.0, min(240.0, float(os.getenv(
            "CONTENT_FACTORY_CARTOON_FAST_RESCUE_TIMEOUT" if rescue else "CONTENT_FACTORY_CARTOON_FAST_TIMEOUT",
            timeout_default,
        ))))
        num_ctx = max(2048, min(4096, int(os.getenv(
            "CONTENT_FACTORY_CARTOON_FAST_NUM_CTX", "3072" if not rescue else "2304"
        ))))
        num_predict = max(320, min(1200, int(os.getenv(
            "CONTENT_FACTORY_CARTOON_FAST_NUM_PREDICT", "700" if not rescue else "480"
        ))))
        fast_model = os.getenv("CONTENT_FACTORY_CARTOON_FAST_MODEL", self._model).strip() or self._model
        payload: dict[str, object] = {
            "model": fast_model,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "format": "json",
            "options": {
                "temperature": 0.65 if not rescue else 0.45,
                "num_ctx": num_ctx,
                "num_predict": num_predict,
                "num_thread": max(2, min(8, int(os.getenv("CONTENT_FACTORY_CARTOON_NUM_THREAD", "4")))),
            },
            "keep_alive": "15m",
        }
        if system_prompt is not None:
            payload["system"] = system_prompt
        data = await self._post_generate_with_timeout(payload, timeout=timeout)
        text = data.get("response")
        if not isinstance(text, str):
            raise RuntimeError("Ollama fast creative response is missing string 'response'.")
        try:
            return response_model.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ValueError(
                "Ollama fast creative JSON failed validation. "
                f"Response: {text[:1200]}"
            ) from exc

    async def _post_generate_with_timeout(
        self,
        payload: dict[str, object],
        *,
        timeout: float,
    ) -> dict[str, object]:
        url = f"{self._base_url}/api/generate"
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                response = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"Ollama fast call timed out after {timeout:.0f}s ({exc.__class__.__name__}). "
                f"Model: {payload.get('model', self._model)}"
            ) from exc
        except httpx.RequestError as exc:
            raise RuntimeError(
                f"Unable to reach local Ollama fast path: {str(exc) or exc.__class__.__name__}. "
                f"Model: {payload.get('model', self._model)}"
            ) from exc
        if response.is_error:
            raise RuntimeError(
                f"Ollama fast call failed HTTP {response.status_code}: {response.text[:1000]}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Ollama fast call returned non-JSON HTTP body: {response.text[:800]}") from exc
        if not isinstance(data, dict):
            raise RuntimeError("Ollama fast call returned unexpected response type.")
        return data

    async def generate_structured(
        self,
        prompt: str,
        response_model: type[ModelT],
        *,
        system_prompt: str | None = None,
        max_retries: int = 1,
    ) -> ModelT:
        schema = response_model.model_json_schema()
        current_prompt = prompt

        # V17.2: Hindi comedy batches carry scene briefs + continuity +
        # structured schema. 3072 was too small for the ~12k-char V17.1
        # prompts and could truncate/derail structured output.
        num_ctx = max(
            4096,
            min(
                8192,
                int(
                    os.getenv(
                        "CONTENT_FACTORY_CARTOON_NUM_CTX",
                        "6144",
                    )
                ),
            ),
        )

        num_predict = max(
            1000,
            min(
                3200,
                int(
                    os.getenv(
                        "CONTENT_FACTORY_CARTOON_NUM_PREDICT",
                        "2300",
                    )
                ),
            ),
        )

        num_thread = max(
            2,
            min(
                8,
                int(
                    os.getenv(
                        "CONTENT_FACTORY_CARTOON_NUM_THREAD",
                        "4",
                    )
                ),
            ),
        )

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
                    "num_ctx": num_ctx,
                    "num_predict": num_predict,
                    "num_thread": num_thread,
                },
                "keep_alive": "15m",
            }

            if system_prompt is not None:
                payload[
                    "system"
                ] = system_prompt

            try:
                data = await self._post_generate(payload)
            except Exception as exc:
                if attempt >= max_retries:
                    raise
                print(
                    "[CARTOON LLM V17.2] "
                    f"attempt={attempt + 1}; transport_error={type(exc).__name__}; retry=YES"
                )
                # Retry the SAME grounded prompt; do not throw away scene briefs.
                current_prompt = prompt
                continue

            response_text = data.get(
                "response"
            )

            if not isinstance(
                response_text,
                str,
            ):
                raise RuntimeError(
                    "Ollama returned an invalid cartoon structured response: "
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
                        "Ollama failed to produce valid cartoon structured "
                        f"output after {max_retries + 1} attempt(s). "
                        f"Last response: {response_text[:1000]}"
                    ) from exc

                # V17.2: the old retry discarded the original scene briefs,
                # so the model had no grounded content on attempt 2. Preserve the
                # original prompt and add only a compact structured-output reminder.
                current_prompt = (
                    prompt
                    + "\n\nV17.2 STRUCTURED RETRY: Return only valid JSON for the supplied schema. "
                    "Preserve every requested scene ID, location ID and character ID. "
                    "Keep each dialogue line concise enough that the complete batch fits. "
                    "No markdown and no explanation."
                )
                print(
                    "[CARTOON LLM V17.2] "
                    f"attempt={attempt + 1}; structured_validation_retry=YES"
                )

        raise RuntimeError(
            "Unreachable cartoon Ollama execution state."
        )

    def tuning(self) -> dict[str, int]:
        return {
            "num_ctx": max(
                4096,
                min(
                    8192,
                    int(
                        os.getenv(
                            "CONTENT_FACTORY_CARTOON_NUM_CTX",
                            "6144",
                        )
                    ),
                ),
            ),
            "num_predict": max(
                1000,
                min(
                    3200,
                    int(
                        os.getenv(
                            "CONTENT_FACTORY_CARTOON_NUM_PREDICT",
                            "2300",
                        )
                    ),
                ),
            ),
            "num_thread": max(
                2,
                min(
                    8,
                    int(
                        os.getenv(
                            "CONTENT_FACTORY_CARTOON_NUM_THREAD",
                            "4",
                        )
                    ),
                ),
            ),
        }
