from abc import ABC, abstractmethod

from content_factory.orchestration.state import WorkflowState


class Agent(ABC):
    """Base interface for all workflow agents."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable agent name."""
        ...

    @abstractmethod
    async def execute(
        self,
        state: WorkflowState,
    ) -> WorkflowState:
        """Execute the agent against shared workflow state."""
        ...
