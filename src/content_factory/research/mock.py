from content_factory.models.content import ResearchEvidence
from content_factory.research.base import ResearchService


class MockResearchService(ResearchService):
    """Deterministic research service for development."""

    async def search(
        self,
        query: str,
    ) -> list[ResearchEvidence]:
        """Return representative research evidence."""
        return [
            ResearchEvidence(
                title="AI Agents for Software Testing",
                source="YouTube",
                url="https://example.com/video-1",
                published_at="2026-08-10",
                engagement_score=92.0,
            ),
            ResearchEvidence(
                title="How AI Is Changing Test Automation",
                source="YouTube",
                url="https://example.com/video-2",
                published_at="2026-08-11",
                engagement_score=88.0,
            ),
            ResearchEvidence(
                title="Local LLMs for Developers",
                source="YouTube",
                url="https://example.com/video-3",
                published_at="2026-08-12",
                engagement_score=85.0,
            ),
        ]
