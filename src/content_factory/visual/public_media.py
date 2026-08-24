from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


GENERIC_QUERY_TERMS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "about",
    "explained",
    "update",
    "scene",
    "world",
    "championship",
    "championships",
    "today",
    "latest",
    "current",
    "context",
    "guide",
    "review",
    "news",
    "photo",
    "image",
    "match",
    "tournament",
    "event",
    "story",
}


@dataclass
class PublicMediaResult:
    title: str
    source_page: str
    license_name: str
    author: str
    image_url: str
    page_id: str
    relevance_score: float = 0.0
    matched_terms: tuple[str, ...] = ()


class WikimediaCommonsProvider:
    """
    Key-free reusable public-image lookup with semantic relevance gating.

    A candidate can be sharp and licensed but still be wrong for the topic.
    V8.2 rejects those candidates before download/acceptance.
    """

    API_URL = "https://commons.wikimedia.org/w/api.php"

    def __init__(self) -> None:
        self._used_ids: set[str] = set()

    async def fetch(
        self,
        query: str,
        output_path: str,
    ) -> PublicMediaResult | None:
        results = await self.fetch_many(
            query=query,
            output_paths=[
                output_path,
            ],
            limit=1,
        )

        return (
            results[0]
            if results
            else None
        )

    async def fetch_many(
        self,
        *,
        query: str,
        output_paths: list[str],
        limit: int = 3,
    ) -> list[PublicMediaResult]:
        """
        Fetch several DISTINCT, relevance-gated, reusable photos using ONE
        Wikimedia search request.

        This is the foundation for real B-roll micro-cuts. It does not weaken
        the semantic relevance or license filters.
        """
        query = self._clean_query(
            query
        )

        if not query:
            return []

        requested = max(
            1,
            min(
                int(
                    limit
                ),
                len(
                    output_paths
                ),
                3,
            ),
        )

        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": "6",
            "gsrlimit": "40",
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|size",
            "iiurlwidth": "2200",
            "origin": "*",
        }

        accepted: list[
            PublicMediaResult
        ] = []

        try:
            async with httpx.AsyncClient(
                timeout=24.0,
                follow_redirects=True,
                trust_env=False,
                headers={
                    "User-Agent": "AgenticContentFactory/8.7"
                },
            ) as client:
                response = await client.get(
                    self.API_URL,
                    params=params,
                )
                response.raise_for_status()
                payload = response.json()

                pages = list(
                    payload.get(
                        "query",
                        {},
                    ).get(
                        "pages",
                        {},
                    ).values()
                )

                ranked = []

                for page in pages:
                    relevance = self._semantic_relevance(
                        page,
                        query,
                    )

                    if not relevance[
                        "acceptable"
                    ]:
                        continue

                    ranked.append(
                        (
                            float(
                                relevance[
                                    "score"
                                ]
                            ),
                            page,
                            relevance,
                        )
                    )

                ranked.sort(
                    key=lambda item: item[0],
                    reverse=True,
                )

                output_index = 0

                for _, page, relevance in ranked:
                    if output_index >= requested:
                        break

                    page_id = str(
                        page.get(
                            "pageid",
                            "",
                        )
                    )

                    if (
                        page_id
                        and page_id in self._used_ids
                    ):
                        continue

                    result = await self._download_candidate(
                        client,
                        page,
                        output_paths[
                            output_index
                        ],
                        relevance_score=float(
                            relevance[
                                "score"
                            ]
                        ),
                        matched_terms=tuple(
                            relevance[
                                "matched_terms"
                            ]
                        ),
                    )

                    if result is None:
                        continue

                    if result.page_id:
                        self._used_ids.add(
                            result.page_id
                        )

                    self._write_attribution(
                        output_paths[
                            output_index
                        ],
                        result,
                    )

                    accepted.append(
                        result
                    )
                    output_index += 1

        except Exception as exc:
            print(
                "[VISUAL QA] Wikimedia multi-shot lookup unavailable: "
                f"{exc.__class__.__name__}"
            )

        return accepted

    async def _download_candidate(
        self,
        client: httpx.AsyncClient,
        page: dict[str, Any],
        output_path: str,
        *,
        relevance_score: float,
        matched_terms: tuple[str, ...],
    ) -> PublicMediaResult | None:
        info_list = page.get(
            "imageinfo"
        ) or []

        if not info_list:
            return None

        info = info_list[0]
        metadata = info.get(
            "extmetadata"
        ) or {}

        license_name = self._meta(
            metadata,
            "LicenseShortName",
        )

        if not self._license_allowed(
            license_name
        ):
            return None

        media_type = self._meta(
            metadata,
            "MediaType",
        ).lower()

        if media_type and media_type not in {
            "bitmap",
            "drawing",
            "photograph",
            "image",
        }:
            return None

        width = int(
            info.get(
                "width",
                0,
            )
            or 0
        )
        height = int(
            info.get(
                "height",
                0,
            )
            or 0
        )

        if (
            width
            and height
            and (
                width < 900
                or height < 500
            )
        ):
            return None

        image_url = (
            info.get(
                "thumburl"
            )
            or info.get(
                "url"
            )
        )

        if not image_url:
            return None

        try:
            response = await client.get(
                image_url
            )
            response.raise_for_status()
        except Exception:
            return None

        content_type = response.headers.get(
            "content-type",
            "",
        ).lower()

        if "image/" not in content_type:
            return None

        path = Path(
            output_path
        )
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        path.write_bytes(
            response.content
        )

        page_id = str(
            page.get(
                "pageid",
                "",
            )
        )

        return PublicMediaResult(
            title=str(
                page.get(
                    "title"
                )
                or ""
            ).removeprefix(
                "File:"
            ),
            source_page=(
                f"https://commons.wikimedia.org/?curid={page_id}"
                if page_id
                else "https://commons.wikimedia.org/"
            ),
            license_name=license_name,
            author=self._strip_html(
                self._meta(
                    metadata,
                    "Artist",
                )
                or self._meta(
                    metadata,
                    "Credit",
                )
                or "Wikimedia Commons contributor"
            ),
            image_url=image_url,
            page_id=page_id,
            relevance_score=relevance_score,
            matched_terms=matched_terms,
        )

    @classmethod
    def _semantic_relevance(
        cls,
        page: dict[str, Any],
        query: str,
    ) -> dict[str, Any]:
        title = str(
            page.get(
                "title",
                "",
            )
        ).lower()

        info = (
            (
                page.get(
                    "imageinfo"
                )
                or [
                    {}
                ]
            )[0]
        )
        metadata = info.get(
            "extmetadata"
        ) or {}

        description = cls._strip_html(
            cls._meta(
                metadata,
                "ImageDescription",
            )
            or cls._meta(
                metadata,
                "ObjectName",
            )
            or ""
        ).lower()

        haystack = (
            title
            + " "
            + description
        )

        hay_tokens = set(
            re.findall(
                r"[a-zà-ÿ0-9]{3,}",
                haystack,
            )
        )

        query_tokens = [
            token
            for token in re.findall(
                r"[a-zà-ÿ0-9]{3,}",
                query.lower(),
            )
        ]

        strong_tokens = [
            token
            for token in query_tokens
            if token
            not in GENERIC_QUERY_TERMS
        ]

        generic_tokens = [
            token
            for token in query_tokens
            if token
            in GENERIC_QUERY_TERMS
        ]

        strong_matches = [
            token
            for token in strong_tokens
            if token in hay_tokens
        ]

        generic_matches = [
            token
            for token in generic_tokens
            if token in hay_tokens
        ]

        # Example:
        # Badminton World Championship query must match "badminton".
        # A generic football World Championship photo is rejected.
        if (
            strong_tokens
            and not strong_matches
        ):
            return {
                "acceptable": False,
                "score": 0.0,
                "matched_terms": [],
            }

        if (
            not strong_tokens
            and not generic_matches
        ):
            return {
                "acceptable": False,
                "score": 0.0,
                "matched_terms": [],
            }

        score = (
            len(
                strong_matches
            )
            * 12.0
            + len(
                generic_matches
            )
            * 2.0
        )

        undesirable = (
            "logo",
            "flag",
            "icon",
            "signature",
            "coat of arms",
            "seal",
            "poster",
        )

        if any(
            marker in title
            for marker in undesirable
        ):
            score -= 7.0

        width = float(
            info.get(
                "width",
                0,
            )
            or 0
        )
        height = float(
            info.get(
                "height",
                0,
            )
            or 0
        )

        if (
            width >= 1600
            and height >= 900
        ):
            score += 2.0

        return {
            "acceptable": score > 0,
            "score": score,
            "matched_terms": (
                strong_matches
                + generic_matches
            )[
                :8
            ],
        }

    @classmethod
    def _candidate_score(
        cls,
        page: dict[str, Any],
        query: str,
    ) -> float:
        return float(
            cls._semantic_relevance(
                page,
                query,
            )[
                "score"
            ]
        )

    @staticmethod
    def _clean_query(
        text: str,
    ) -> str:
        text = re.sub(
            r"\s+",
            " ",
            text,
        ).strip()

        words = [
            word.strip(
                ".,:;!?()[]{}\"'"
            )
            for word in text.split()
        ]

        words = [
            word
            for word in words
            if len(
                word
            )
            >= 2
        ]

        return " ".join(
            words[
                :10
            ]
        )

    @staticmethod
    def _meta(
        metadata: dict[str, Any],
        key: str,
    ) -> str:
        value = (
            metadata.get(
                key
            )
            or {}
        )

        if isinstance(
            value,
            dict,
        ):
            return str(
                value.get(
                    "value"
                )
                or ""
            ).strip()

        return str(
            value
            or ""
        ).strip()

    @staticmethod
    def _license_allowed(
        value: str,
    ) -> bool:
        text = (
            value.lower()
            .strip()
        )

        if not text:
            return False

        blocked = (
            "fair use",
            "non-free",
            "nonfree",
            "all rights reserved",
            "cc by-nc",
            "cc-by-nc",
            "by-nc",
            "non-commercial",
            "noncommercial",
            "cc by-nd",
            "cc-by-nd",
            "by-nd",
            "no derivatives",
            "no-derivatives",
        )

        if any(
            marker in text
            for marker in blocked
        ):
            return False

        allowed = (
            "cc by",
            "cc-by",
            "cc0",
            "public domain",
            "gfdl",
        )

        return any(
            marker in text
            for marker in allowed
        )

    @staticmethod
    def _strip_html(
        value: str,
    ) -> str:
        value = re.sub(
            r"<[^>]+>",
            " ",
            value,
        )

        return html.unescape(
            re.sub(
                r"\s+",
                " ",
                value,
            )
        ).strip()

    @staticmethod
    def _write_attribution(
        output_path: str,
        result: PublicMediaResult,
    ) -> None:
        path = Path(
            output_path
        )

        sidecar = path.with_suffix(
            path.suffix
            + ".source.json"
        )

        sidecar.write_text(
            json.dumps(
                {
                    "source": "Wikimedia Commons",
                    "title": result.title,
                    "source_page": result.source_page,
                    "license": result.license_name,
                    "author": result.author,
                    "image_url": result.image_url,
                    "page_id": result.page_id,
                    "relevance_score": (
                        result.relevance_score
                    ),
                    "matched_terms": list(
                        result.matched_terms
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        attribution = (
            path.parent
            / "ATTRIBUTION.md"
        )

        with attribution.open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write(
                f"- **{path.name}** — "
                f"{result.title}; "
                f"{result.author}; "
                f"{result.license_name}; "
                f"{result.source_page}; "
                f"matched={','.join(result.matched_terms)}\n"
            )
