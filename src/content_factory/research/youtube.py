from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from yt_dlp import YoutubeDL

from content_factory.models.content import ResearchEvidence
from content_factory.research.base import ResearchService
from content_factory.utils.unicode_tokens import unicode_token_set


class _QuietYTDLPLogger:
    def debug(
        self,
        msg: str,
    ) -> None:
        return None

    def warning(
        self,
        msg: str,
    ) -> None:
        return None

    def error(
        self,
        msg: str,
    ) -> None:
        return None


class YouTubeResearchService(ResearchService):
    """
    Fast public YouTube metadata validation via yt-dlp.

    Previous implementations could inspect max_results*3 entries; with a
    default max_results of 20 that meant as many as 60 results PER trend.

    V8.3:
    1. Search recent results first (normally 10).
    2. If recent search already has >=3 query-relevant titles, stop.
    3. Only then run a normal relevance-search fallback.
    4. Scoring still receives enough evidence for its top-5 calculation.
    """

    def __init__(
        self,
        *,
        max_results: int = 20,
        timeout: float = 30.0,
        lookback_days: int = 7,
    ) -> None:
        self._max_results = max(
            1,
            int(
                max_results
            ),
        )
        self._timeout = max(
            5.0,
            min(
                float(
                    timeout
                ),
                15.0,
            ),
        )
        self._lookback_days = max(
            1,
            int(
                lookback_days
            ),
        )

        # Scoring only uses the strongest ~5 items. 10 gives redundancy while
        # avoiding dozens of expensive metadata extractions.
        self._search_limit = max(
            8,
            min(
                12,
                self._max_results,
            ),
        )

    async def search(
        self,
        query: str,
    ) -> list[ResearchEvidence]:
        query = (
            query
            or ""
        ).strip()

        if not query:
            return []

        return await asyncio.to_thread(
            self._search_sync,
            query,
        )

    def _search_sync(
        self,
        query: str,
    ) -> list[ResearchEvidence]:
        recent = self._run_search(
            f"ytsearchdate{self._search_limit}:{query}"
        )

        recent_records = self._build_records(
            recent
        )

        relevant_recent = [
            item
            for item in recent_records
            if self._title_relevance(
                query,
                item.title,
            )
            >= self._relevance_threshold(
                query
            )
        ]

        # Most trend candidates finish here: one yt-dlp search instead of
        # recent + normal + oversized result sets.
        if len(
            relevant_recent
        ) >= 3:
            return recent_records[
                :self._search_limit
            ]

        normal = self._run_search(
            f"ytsearch{self._search_limit}:{query}"
        )

        merged = self._merge_entries(
            recent,
            normal,
        )

        return self._build_records(
            merged
        )[
            :self._search_limit
        ]

    def _run_search(
        self,
        target: str,
    ) -> list[dict[str, Any]]:
        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "ignoreerrors": True,
            "noplaylist": True,
            "playlistend": self._search_limit,
            "socket_timeout": self._timeout,
            "retries": 1,
            "extractor_retries": 1,
            "fragment_retries": 1,
            "logger": _QuietYTDLPLogger(),
        }

        try:
            with YoutubeDL(
                options
            ) as ydl:
                result = ydl.extract_info(
                    target,
                    download=False,
                )
        except Exception as exc:
            print(
                f"[YOUTUBE] Search failed: "
                f"{exc.__class__.__name__}"
            )
            return []

        if not isinstance(
            result,
            dict,
        ):
            return []

        entries = result.get(
            "entries",
            [],
        )

        if not isinstance(
            entries,
            list,
        ):
            return []

        return [
            item
            for item in entries
            if isinstance(
                item,
                dict,
            )
        ]

    def _build_records(
        self,
        entries: list[
            dict[str, Any]
        ],
    ) -> list[ResearchEvidence]:
        cutoff = (
            datetime.now(
                timezone.utc
            )
            - timedelta(
                days=self._lookback_days
            )
        )

        result = []
        fallback = []
        seen = set()

        for item in entries:
            title = str(
                item.get(
                    "title"
                )
                or ""
            ).strip()

            if not title:
                continue

            video_id = str(
                item.get(
                    "id"
                )
                or ""
            ).strip()

            url = item.get(
                "webpage_url"
            )

            if not isinstance(
                url,
                str,
            ) or not url.startswith(
                "http"
            ):
                if not video_id:
                    continue
                url = (
                    "https://www.youtube.com/watch?v="
                    + video_id
                )

            if url in seen:
                continue

            seen.add(
                url
            )

            published_at = self._published_at(
                item
            )

            record = ResearchEvidence(
                title=title,
                source="YouTube",
                url=url,
                published_at=published_at,
                engagement_score=float(
                    self._int_value(
                        item.get(
                            "view_count"
                        )
                    )
                ),
                view_count=self._int_value(
                    item.get(
                        "view_count"
                    )
                ),
                like_count=self._int_value(
                    item.get(
                        "like_count"
                    )
                ),
                comment_count=self._int_value(
                    item.get(
                        "comment_count"
                    )
                ),
                channel=(
                    item.get(
                        "channel"
                    )
                    or item.get(
                        "uploader"
                    )
                ),
                duration_seconds=self._optional_int(
                    item.get(
                        "duration"
                    )
                ),
            )

            fallback.append(
                record
            )

            published = self._parse_datetime(
                published_at
            )

            if (
                published is not None
                and published >= cutoff
            ):
                result.append(
                    record
                )

        # TrendResearchAgent applies its own fresh/relevance filter again.
        # When upload dates are unavailable, returning fallback metadata is
        # better than throwing away the candidate.
        return (
            result
            if result
            else fallback
        )

    @staticmethod
    def _merge_entries(
        first: list[
            dict[str, Any]
        ],
        second: list[
            dict[str, Any]
        ],
    ) -> list[
        dict[str, Any]
    ]:
        merged = []
        seen = set()

        for item in [
            *first,
            *second,
        ]:
            key = str(
                item.get(
                    "id"
                )
                or item.get(
                    "webpage_url"
                )
                or item.get(
                    "title"
                )
                or ""
            )

            if not key or key in seen:
                continue

            seen.add(
                key
            )
            merged.append(
                item
            )

        return merged

    @classmethod
    def _title_relevance(
        cls,
        query: str,
        title: str,
    ) -> float:
        query_tokens = cls._tokens(
            query
        )
        title_tokens = cls._tokens(
            title
        )

        if (
            not query_tokens
            or not title_tokens
        ):
            return 0.0

        overlap = len(
            query_tokens
            & title_tokens
        )

        return min(
            1.0,
            overlap
            / len(
                query_tokens
            ),
        )

    @classmethod
    def _relevance_threshold(
        cls,
        query: str,
    ) -> float:
        count = len(
            cls._tokens(
                query
            )
        )

        if count <= 1:
            return 1.0

        if count == 2:
            return 0.50

        return 0.40

    @staticmethod
    def _tokens(
        text: str,
    ) -> set[str]:
        return unicode_token_set(
            text,
            min_length=2,
        )

    @staticmethod
    def _published_at(
        item: dict[
            str,
            Any,
        ],
    ) -> str | None:
        timestamp = (
            item.get(
                "timestamp"
            )
            or item.get(
                "release_timestamp"
            )
        )

        if timestamp is not None:
            try:
                return datetime.fromtimestamp(
                    float(
                        timestamp
                    ),
                    tz=timezone.utc,
                ).isoformat()
            except (
                TypeError,
                ValueError,
                OSError,
            ):
                pass

        upload_date = item.get(
            "upload_date"
        )

        if upload_date:
            try:
                return datetime.strptime(
                    str(
                        upload_date
                    ),
                    "%Y%m%d",
                ).replace(
                    tzinfo=timezone.utc
                ).isoformat()
            except ValueError:
                pass

        return None

    @staticmethod
    def _parse_datetime(
        value: str | None,
    ) -> datetime | None:
        if not value:
            return None

        try:
            parsed = datetime.fromisoformat(
                value.replace(
                    "Z",
                    "+00:00",
                )
            )

            if parsed.tzinfo is None:
                parsed = parsed.replace(
                    tzinfo=timezone.utc
                )

            return parsed

        except ValueError:
            return None

    @staticmethod
    def _int_value(
        value: Any,
    ) -> int:
        try:
            return max(
                int(
                    value
                    or 0
                ),
                0,
            )
        except (
            TypeError,
            ValueError,
        ):
            return 0

    @staticmethod
    def _optional_int(
        value: Any,
    ) -> int | None:
        if value is None:
            return None

        try:
            return max(
                int(
                    value
                ),
                0,
            )
        except (
            TypeError,
            ValueError,
        ):
            return None
