import json
from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel, ValidationError

ModelT = TypeVar("ModelT", bound=BaseModel)


class LLMProvider(ABC):
    """Provider abstraction for language models."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> str:
        """Generate a text response."""
        ...

    async def generate_structured(
        self,
        prompt: str,
        response_model: type[ModelT],
        *,
        system_prompt: str | None = None,
        max_retries: int = 2,
    ) -> ModelT:
        """Generate and validate a structured response."""
        current_prompt = prompt

        for attempt in range(max_retries + 1):
            response = await self.generate(
                current_prompt,
                system_prompt=system_prompt,
            )

            try:
                payload = json.loads(response)

                return response_model.model_validate(payload)

            except (json.JSONDecodeError, ValidationError) as exc:
                if attempt >= max_retries:
                    raise ValueError(
                        "LLM failed to produce valid structured output "
                        f"after {max_retries + 1} attempts.",
                    ) from exc

                current_prompt = self._build_repair_prompt(
                    prompt=prompt,
                    response=response,
                    error=str(exc),
                    response_model=response_model,
                )

        raise RuntimeError("Unreachable LLM execution state.")

    @staticmethod
    def _build_repair_prompt(
        *,
        prompt: str,
        response: str,
        error: str,
        response_model: type[ModelT],
    ) -> str:
        """Build a prompt asking the LLM to repair invalid output."""
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
{json.dumps(schema, indent=2)}

Return ONLY one valid JSON object matching this schema.

Do not use markdown.
Do not add explanations.
Do not add extra fields.
Do not wrap the object inside another object.
"""
