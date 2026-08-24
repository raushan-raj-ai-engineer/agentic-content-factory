from __future__ import annotations

from typing import Any

from content_factory.agents.base import Agent
from content_factory.orchestration.state import WorkflowState


class ModelMemoryReleaseAgent(Agent):
    """Release text-model memory before local media generation."""

    def __init__(
        self,
        llm: Any,
    ) -> None:
        self._llm = llm

    @property
    def name(self) -> str:
        return "Model Memory Release Agent"

    async def execute(
        self,
        state: WorkflowState,
    ) -> WorkflowState:
        release = getattr(
            self._llm,
            "release",
            None,
        )

        if callable(release):
            result = release()
            if hasattr(
                result,
                "__await__",
            ):
                await result

        state.status = "text_model_released"
        return state
