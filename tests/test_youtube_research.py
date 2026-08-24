import httpx
import pytest

from content_factory.research.youtube import YouTubeResearchService


@pytest.mark.asyncio
async def test_search_returns_video_evidence() -> None:
    """Search should convert YouTube API data into evidence."""
    responses = [
        httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": {
                            "videoId": "abc123",
                        },
                    },
                ],
            },
        ),
        httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "abc123",
                        "snippet": {
                            "title": "AI Agents for Testing",
                            "publishedAt": "2026-08-10T10:00:00Z",
                        },
                        "statistics": {
                            "viewCount": "125000",
                        },
                    },
                ],
            },
        ),
    ]

    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        return responses.pop(0)

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(
        transport=transport,
    ) as client:
        service = YouTubeResearchService(
            api_key="test-key",
            client=client,
        )

        results = await service.search(
            "AI agents software testing",
        )

    assert len(results) == 1
    assert results[0].title == "AI Agents for Testing"
    assert results[0].source == "YouTube"
    assert results[0].engagement_score == 125000.0
    assert results[0].url == ("https://www.youtube.com/watch?v=abc123")


@pytest.mark.asyncio
async def test_search_returns_empty_when_no_videos() -> None:
    """Search should return empty evidence when no videos exist."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "items": [],
            },
        ),
    )

    async with httpx.AsyncClient(
        transport=transport,
    ) as client:
        service = YouTubeResearchService(
            api_key="test-key",
            client=client,
        )

        results = await service.search(
            "nonexistent topic",
        )

    assert results == []


@pytest.mark.asyncio
async def test_search_raises_for_http_error() -> None:
    """Search should propagate YouTube HTTP errors."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            403,
            json={
                "error": {
                    "message": "API key invalid",
                },
            },
        ),
    )

    async with httpx.AsyncClient(
        transport=transport,
    ) as client:
        service = YouTubeResearchService(
            api_key="invalid-key",
            client=client,
        )

        with pytest.raises(httpx.HTTPStatusError):
            await service.search("AI testing")


def test_missing_api_key_raises_error() -> None:
    """Service should reject an empty API key."""
    with pytest.raises(
        ValueError,
        match="YOUTUBE_API_KEY is required",
    ):
        YouTubeResearchService(
            api_key="",
        )
