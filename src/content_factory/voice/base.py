from abc import ABC, abstractmethod


class VoiceProvider(ABC):
    """Provider-independent voice generation abstraction."""

    @abstractmethod
    async def generate(
        self,
        text: str,
        output_path: str,
    ) -> int:
        """Generate speech and return duration in seconds."""
        ...
