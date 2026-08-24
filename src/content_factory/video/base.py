from abc import ABC, abstractmethod


class VideoAssembler(ABC):
    """Provider-independent video assembly interface."""

    @abstractmethod
    async def assemble(
        self,
        voice_files: list[str],
        visual_files: list[str],
        output_path: str,
    ) -> int:
        """Assemble narration and visuals and return duration in seconds."""
        ...
