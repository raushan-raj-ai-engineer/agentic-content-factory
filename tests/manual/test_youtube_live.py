import pytest

from content_factory.config.settings import Settings
from content_factory.research.youtube import YouTubeResearchService


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_youtube_search() -> None:
    """Manual live test against YouTube Data API."""
    settings = Settings()

    service = YouTubeResearchService(
        api_key=settings.youtube_api_key,
        max_results=5,
        timeout=settings.youtube_timeout,
    )

    results = await service.search(
        "AI agents software testing",
    )

    assert results

    for result in results:
        print()
        print(f"Title: {result.title}")
        print(f"Source: {result.source}")
        print(f"URL: {result.url}")
        print(f"Published: {result.published_at}")
        print(f"Views: {result.engagement_score}")
