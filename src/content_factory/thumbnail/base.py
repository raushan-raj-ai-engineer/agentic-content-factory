from abc import ABC, abstractmethod


class ThumbnailGenerator(ABC):
    """Provider-independent thumbnail generation interface."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        output_path: str,
    ) -> None:
        """Generate a thumbnail artifact."""
        ...
