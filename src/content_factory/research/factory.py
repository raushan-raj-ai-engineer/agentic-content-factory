from content_factory.config.settings import Settings
from content_factory.research.base import ResearchService
from content_factory.research.mock import MockResearchService
from content_factory.research.youtube import YouTubeResearchService


def create_research_service(
    settings: Settings,
) -> ResearchService:
    """Create the configured research service."""
    if settings.research_provider in {"youtube", "youtube_local"}:
        return YouTubeResearchService(
            max_results=settings.youtube_max_results,
            timeout=settings.youtube_timeout,
            lookback_days=settings.trend_lookback_days,
        )

    if settings.research_provider == "mock":
        return MockResearchService()

    raise ValueError(
        f"Unsupported research provider: {settings.research_provider}",
    )
