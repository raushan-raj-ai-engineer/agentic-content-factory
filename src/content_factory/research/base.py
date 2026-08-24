from abc import ABC, abstractmethod

from content_factory.models.content import ResearchEvidence


class ResearchService(ABC):
    """External research service abstraction."""

    @abstractmethod
    async def search(
        self,
        query: str,
    ) -> list[ResearchEvidence]:
        """Search external sources."""
        ...
