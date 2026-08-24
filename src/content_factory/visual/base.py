from abc import ABC, abstractmethod


class VisualProvider(ABC):
    """Provider-independent visual generation interface."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        output_path: str,
        *,
        title: str | None = None,
        description: str | None = None,
        visual_type: str | None = None,
    ) -> None:
        """Generate one visual artifact."""
        ...
