from __future__ import annotations

import asyncio
import math
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

import httpx

from content_factory.agents.base import Agent
from content_factory.llm.base import LLMProvider
from content_factory.models.content import ResearchPlan
from content_factory.orchestration.state import WorkflowState
from content_factory.research.trend_signals import (
    DiscoverySignal,
    clear_signals,
    set_signal,
)
from content_factory.research.language_market import (
    configured_markets,
    detect_language,
    load_language_market_config,
    market_profile,
)
from content_factory.research.topic_quality import (
    is_calendar_only_topic,
)
from content_factory.utils.unicode_tokens import (
    unicode_token_set,
    unicode_tokens,
)


AUTO_SENTINELS = {
    "auto",
    "automatic",
    "__auto__",
    "trending",
    "trend",
}

STOP_WORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for",
    "with", "from", "at", "by", "is", "are", "was", "were", "be",
    "this", "that", "as", "it", "its", "new", "latest", "today",
}

GENERIC_ONE_WORD_TOPICS = {
    "sec",
    "teacher",
    "news",
    "live",
    "update",
    "result",
    "results",
    "match",
    "weather",
    "video",
    "viral",
    "trend",
    "trending",
    "breaking",
    # Common generic trend words in Indian-language feeds.
    "ന്യൂസ്",
    "समाचार",
    "खबर",
    "अपडेट",
    "செய்திகள்",
    "செய்தி",
    "ಸುದ್ದಿ",
    "સમાચાર",
    "খবর",
    "সংবাদ",
}

PUBLISHER_SUFFIXES = {
    "moneycontrol",
    "ndtv",
    "reuters",
    "cnn",
    "bbc",
    "cnbc",
    "forbes",
    "bloomberg",
    "indiatoday",
    "firstpost",
    "livemint",
    "thehindu",
    "news18",
}

SPECIAL_CASE = {
    "ai": "AI",
    "gta": "GTA",
    "mcp": "MCP",
    "sec": "SEC",
    "ipo": "IPO",
    "nfl": "NFL",
    "nba": "NBA",
    "usa": "USA",
    "uk": "UK",
}


@dataclass
class _TrendSeed:
    title: str
    traffic: int
    rank: int
    related_titles: list[str] = field(default_factory=list)
    market_geo: str = "IN"
    market_name: str = "India"


class ResearchPlannerAgent(Agent):
    """Discover real public trends and normalize them before YouTube validation."""

    def __init__(
        self,
        llm: LLMProvider,
        *,
        mode: str | None = None,
        topic: str | None = None,
        category: str | None = None,
        **_: object,
    ) -> None:
        self._llm = llm
        self._mode = (mode or "").strip().lower()
        self._configured_topic = (
            topic.strip() if isinstance(topic, str) else None
        )
        self._configured_category = (
            category.strip() if isinstance(category, str) else None
        )

    @property
    def name(self) -> str:
        return "Research Planner Agent"

    async def execute(self, state: WorkflowState) -> WorkflowState:
        raw_topic = (
            (state.topic or "").strip()
            or (self._configured_topic or "")
        )
        normalized = raw_topic.lower()

        auto_mode = (
            self._mode == "auto"
            or normalized in AUTO_SENTINELS
            or not raw_topic
        )

        if not auto_mode:
            clear_signals()
            state.research_plan = ResearchPlan(topics=[raw_topic])
            state.status = "research_planned"
            print(f"[RESEARCH] Explicit topic: {raw_topic}")
            return state

        market_mode = (
            os.getenv(
                "CONTENT_FACTORY_MARKET_MODE",
                "global",
            )
            .strip()
            .lower()
        )

        clear_signals()

        if market_mode == "global":
            market_limit = max(
                3,
                min(
                    10,
                    int(
                        os.getenv(
                            "CONTENT_FACTORY_GLOBAL_MARKETS",
                            str(
                                load_language_market_config()[
                                    "scoring"
                                ][
                                    "default_market_count"
                                ]
                            ),
                        )
                    ),
                ),
            )

            markets = configured_markets(
                market_limit
            )

            print(
                "[AUTO] Global language-market discovery enabled: "
                + ", ".join(
                    f"{item['geo']}:{item['default_language']}"
                    for item in markets
                )
            )

            trend_tasks = [
                self._fetch_google_trends(
                    item[
                        "geo"
                    ]
                )
                for item in markets
            ]

            news_tasks = [
                self._fetch_google_news(
                    item[
                        "geo"
                    ],
                    language=item.get(
                        "news_hl"
                    ),
                    ceid=item.get(
                        "news_ceid"
                    ),
                )
                for item in markets
            ]

            results = await asyncio.gather(
                *trend_tasks,
                *news_tasks,
                self._fetch_hacker_news(),
                return_exceptions=True,
            )

            trend_results = results[
                :len(
                    markets
                )
            ]
            news_results = results[
                len(
                    markets
                ):
                len(
                    markets
                )
                * 2
            ]
            hacker_result = results[
                -1
            ]

            google_trends = []
            google_news = []

            for market, result in zip(
                markets,
                trend_results,
            ):
                if isinstance(
                    result,
                    Exception,
                ):
                    continue

                for seed in result:
                    seed.market_geo = market[
                        "geo"
                    ]
                    seed.market_name = market[
                        "name"
                    ]

                google_trends.extend(
                    result
                )

                print(
                    f"[AUTO MARKET] {market['geo']} "
                    f"{market['name']}: "
                    f"{len(result)} trend(s), "
                    f"YouTube reach≈"
                    f"{market['youtube_ad_reach_m']:.1f}M"
                )

            for result in news_results:
                if isinstance(
                    result,
                    Exception,
                ):
                    continue

                google_news.extend(
                    result
                )

            hacker_news = (
                []
                if isinstance(
                    hacker_result,
                    Exception,
                )
                else hacker_result
            )

        else:
            geo = (
                os.getenv(
                    "CONTENT_FACTORY_GEO"
                )
                or "IN"
            ).strip().upper()

            market = market_profile(
                geo
            )

            print(
                f"[AUTO] Single-market discovery enabled "
                f"(geo={geo})"
            )

            google_trends, google_news, hacker_news = await asyncio.gather(
                self._fetch_google_trends(
                    geo
                ),
                self._fetch_google_news(
                    geo,
                    language=market.get(
                        "news_hl"
                    ),
                    ceid=market.get(
                        "news_ceid"
                    ),
                ),
                self._fetch_hacker_news(),
            )

            for seed in google_trends:
                seed.market_geo = geo
                seed.market_name = market[
                    "name"
                ]

        print(
            f"[AUTO SOURCE] Google Trends: "
            f"{len(google_trends)} trend entries"
        )
        print(
            f"[AUTO SOURCE] Google News: "
            f"{len(google_news)} headlines"
        )
        print(
            f"[AUTO SOURCE] Hacker News: "
            f"{len(hacker_news)} top stories"
        )

        candidates = self._score_google_trends(
            google_trends,
            google_news,
            hacker_news,
        )

        candidates = self._merge_cross_market_candidates(
            candidates
        )

        if len(candidates) < 4:
            fallback_topics = await self._topics_from_real_headlines(
                google_news,
                hacker_news,
            )
            for raw_fallback in fallback_topics:
                topic = self._clean_topic(raw_fallback)
                if not topic:
                    continue
                if any(
                    topic.lower() == x.topic.lower()
                    for x in candidates
                ):
                    continue

                news_matches = self._match_count(topic, google_news)
                hn_matches = self._match_count(topic, hacker_news)
                clarity = self._topic_clarity(topic)

                score = min(
                    100.0,
                    (
                        25.0
                        + min(news_matches * 8.0, 40.0)
                        + min(hn_matches * 8.0, 35.0)
                    )
                    * (0.70 + 0.30 * clarity / 100.0),
                )

                sources = []
                if news_matches:
                    sources.append("Google News")
                if hn_matches:
                    sources.append("Hacker News")

                language = detect_language(
                    topic,
                    geo="US",
                )

                candidates.append(
                    DiscoverySignal(
                        topic=topic,
                        raw_topic=raw_fallback,
                        score=round(score, 2),
                        clarity_score=clarity,
                        google_news_matches=news_matches,
                        hacker_news_matches=hn_matches,
                        sources=sources,
                        language_code=language[
                            "code"
                        ],
                        language_name=language[
                            "name"
                        ],
                        market_geo=language[
                            "market_geo"
                        ],
                        market_name=language[
                            "market_name"
                        ],
                        language_priority=float(
                            language[
                                "priority_weight"
                            ]
                        ),
                        language_priority_rank=int(
                            language[
                                "priority_rank"
                            ]
                        ),
                        youtube_market_reach_m=float(
                            language[
                                "youtube_ad_reach_m"
                            ]
                        ),
                    )
                )

        candidates.sort(key=lambda x: x.score, reverse=True)

        candidate_budget = max(
            4,
            min(
                10,
                int(
                    os.getenv(
                        "CONTENT_FACTORY_TREND_CANDIDATES",
                        "7",
                    )
                ),
            ),
        )

        # Hard quality gate: a bare calendar/date label is not a coherent
        # video subject. "21 De Agosto" can match many unrelated uploads
        # simply because they were published on that date.
        hard_filtered = [
            candidate
            for candidate in candidates
            if not is_calendar_only_topic(
                candidate.topic
            )
        ]

        removed_calendar = (
            len(
                candidates
            )
            - len(
                hard_filtered
            )
        )

        # Drop only clearly generic, single-word, unconfirmed trends.
        # Do NOT reject a topic merely because it uses a non-Latin script.
        filtered = [
            candidate
            for candidate in hard_filtered
            if not (
                candidate.clarity_score <= 25
                and candidate.google_news_matches == 0
                and candidate.hacker_news_matches == 0
                and candidate.google_trends_traffic < 5_000
            )
        ]

        pool = (
            filtered
            if len(
                filtered
            ) >= 4
            else hard_filtered
        )

        selected = self._select_language_diverse(
            pool,
            candidate_budget,
        )

        print(
            f"[PERF] Trend candidate budget={candidate_budget}; "
            f"discovered={len(candidates)}, "
            f"calendar_rejected={removed_calendar}, "
            f"after_generic_filter={len(filtered)}"
        )

        if not selected:
            raise RuntimeError(
                "Auto trend discovery could not find usable public trends."
            )

        for signal in selected:
            set_signal(signal)

        state.research_plan = ResearchPlan(
            topics=[x.topic for x in selected]
        )
        state.topic = None
        state.status = "research_planned"

        print("[AUTO] Real trend candidates:")
        for signal in selected:
            raw_suffix = ""
            if (
                signal.raw_topic
                and signal.raw_topic.lower() != signal.topic.lower()
            ):
                raw_suffix = f", raw={signal.raw_topic!r}"

            print(
                f"[AUTO] {signal.topic}: "
                f"discovery={signal.score:.1f}, "
                f"clarity={signal.clarity_score:.0f}, "
                f"google_rank={signal.google_trends_rank or '-'}, "
                f"searches={signal.google_trends_traffic}, "
                f"news={signal.google_news_matches}, "
                f"hn={signal.hacker_news_matches}, "
                f"lang={signal.language_code}/"
                f"{signal.language_name}, "
                f"lang_priority={signal.language_priority:.2f}, "
                f"market={signal.market_geo or '-'}, "
                f"market_mentions={signal.market_mentions}, "
                f"sources={','.join(signal.sources) or '-'}"
                f"{raw_suffix}"
            )

        return state

    async def _fetch_google_trends(self, geo: str) -> list[_TrendSeed]:
        url = f"https://trends.google.com/trending/rss?geo={geo}"

        try:
            async with httpx.AsyncClient(
                timeout=20.0,
                follow_redirects=True,
                trust_env=False,
                headers={
                    "User-Agent": "Mozilla/5.0 AgenticContentFactory/1.0"
                },
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
        except Exception as exc:
            print(
                "[AUTO SOURCE] Google Trends unavailable: "
                f"{exc.__class__.__name__}"
            )
            return []

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError:
            return []

        result: list[_TrendSeed] = []

        for rank, item in enumerate(root.findall(".//item"), start=1):
            title = (item.findtext("title") or "").strip()
            traffic_text = ""
            related_titles: list[str] = []

            for child in item.iter():
                tag = child.tag.lower()
                if tag.endswith("approx_traffic"):
                    traffic_text = (child.text or "").strip()
                elif tag.endswith("news_item_title"):
                    related = (child.text or "").strip()
                    if related:
                        related_titles.append(related)

            if not title:
                continue

            result.append(
                _TrendSeed(
                    title=title,
                    traffic=self._parse_traffic(traffic_text),
                    rank=rank,
                    related_titles=related_titles[:8],
                )
            )

            if len(result) >= 25:
                break

        return result

    async def _fetch_google_news(
        self,
        geo: str,
        *,
        language: str | None = None,
        ceid: str | None = None,
    ) -> list[str]:
        language = (
            language
            or (
                "en-IN"
                if geo == "IN"
                else "en-US"
            )
        )
        ceid = (
            ceid
            or f"{geo}:en"
        )

        url = (
            "https://news.google.com/rss"
            f"?hl={language}&gl={geo}&ceid={ceid}"
        )

        try:
            async with httpx.AsyncClient(
                timeout=20.0,
                follow_redirects=True,
                trust_env=False,
                headers={
                    "User-Agent": "Mozilla/5.0 AgenticContentFactory/1.0"
                },
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
            root = ET.fromstring(response.content)
        except Exception as exc:
            print(
                "[AUTO SOURCE] Google News unavailable: "
                f"{exc.__class__.__name__}"
            )
            return []

        titles: list[str] = []
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            if title:
                titles.append(title)
            if len(titles) >= 50:
                break
        return titles

    async def _fetch_hacker_news(self) -> list[str]:
        base = "https://hacker-news.firebaseio.com/v0"

        try:
            async with httpx.AsyncClient(
                timeout=20.0,
                trust_env=False,
            ) as client:
                ids_response = await client.get(f"{base}/topstories.json")
                ids_response.raise_for_status()
                ids = (ids_response.json() or [])[:30]
                responses = await asyncio.gather(
                    *[
                        client.get(f"{base}/item/{item_id}.json")
                        for item_id in ids
                    ],
                    return_exceptions=True,
                )
        except Exception as exc:
            print(
                "[AUTO SOURCE] Hacker News unavailable: "
                f"{exc.__class__.__name__}"
            )
            return []

        titles: list[str] = []
        for response in responses:
            if isinstance(response, Exception):
                continue
            try:
                data: dict[str, Any] = response.json()
            except Exception:
                continue
            title = str(data.get("title") or "").strip()
            if title:
                titles.append(title)
        return titles

    def _score_google_trends(
        self,
        trends: list[_TrendSeed],
        news: list[str],
        hn: list[str],
    ) -> list[DiscoverySignal]:
        result: list[DiscoverySignal] = []

        for seed in trends:
            topic = self._clean_topic(seed.title)
            if not topic:
                continue

            context_titles = [*news, *seed.related_titles]
            news_matches = self._match_count(topic, context_titles)
            hn_matches = self._match_count(topic, hn)
            clarity = self._topic_clarity(topic)

            rank_score = max(
                0.0,
                30.0 * (1.0 - ((seed.rank - 1) / 25.0)),
            )

            if seed.traffic > 0:
                volume_score = min(
                    50.0,
                    max(
                        5.0,
                        (
                            math.log10(seed.traffic + 1)
                            / 6.0
                        ) * 50.0,
                    ),
                )
            else:
                volume_score = 10.0

            cross_source_score = (
                min(news_matches * 4.0, 12.0)
                + min(hn_matches * 4.0, 8.0)
            )

            raw_score = min(
                100.0,
                rank_score + volume_score + cross_source_score,
            )

            language = detect_language(
                topic,
                geo=seed.market_geo,
            )

            language_share = float(
                load_language_market_config()[
                    "scoring"
                ][
                    "discovery_language_share"
                ]
            )

            market_adjusted = (
                raw_score
                * (
                    1.0
                    - language_share
                )
                + float(
                    language[
                        "priority_weight"
                    ]
                )
                * 100.0
                * language_share
            )

            clarity_factor = (
                0.65
                + 0.35
                * (
                    clarity
                    / 100.0
                )
            )

            score = (
                market_adjusted
                * clarity_factor
            )

            sources = ["Google Trends"]
            if news_matches:
                sources.append("Google News")
            if hn_matches:
                sources.append("Hacker News")

            result.append(
                DiscoverySignal(
                    topic=topic,
                    raw_topic=seed.title,
                    score=round(score, 2),
                    clarity_score=clarity,
                    google_trends_rank=seed.rank,
                    google_trends_traffic=seed.traffic,
                    google_news_matches=news_matches,
                    hacker_news_matches=hn_matches,
                    related_headlines=seed.related_titles,
                    sources=sources,
                    language_code=language[
                        "code"
                    ],
                    language_name=language[
                        "name"
                    ],
                    market_geo=seed.market_geo,
                    market_name=seed.market_name,
                    language_priority=float(
                        language[
                            "priority_weight"
                        ]
                    ),
                    language_priority_rank=int(
                        language[
                            "priority_rank"
                        ]
                    ),
                    youtube_market_reach_m=float(
                        language[
                            "youtube_ad_reach_m"
                        ]
                    ),
                )
            )

        return result

    @staticmethod
    def _merge_cross_market_candidates(
        candidates: list[DiscoverySignal],
    ) -> list[DiscoverySignal]:
        grouped: dict[
            str,
            list[DiscoverySignal],
        ] = {}

        for candidate in candidates:
            grouped.setdefault(
                candidate.topic.strip().lower(),
                [],
            ).append(
                candidate
            )

        merged: list[
            DiscoverySignal
        ] = []

        for group in grouped.values():
            group.sort(
                key=lambda item: item.score,
                reverse=True,
            )

            winner = group[0]
            winner.market_mentions = len(
                {
                    item.market_geo
                    for item in group
                    if item.market_geo
                }
            )

            if winner.market_mentions > 1:
                winner.score = round(
                    min(
                        100.0,
                        winner.score
                        + min(
                            (
                                winner.market_mentions
                                - 1
                            )
                            * 3.0,
                            9.0,
                        ),
                    ),
                    2,
                )

            merged.append(
                winner
            )

        merged.sort(
            key=lambda item: item.score,
            reverse=True,
        )

        return merged

    @staticmethod
    def _select_language_diverse(
        candidates: list[DiscoverySignal],
        budget: int,
    ) -> list[DiscoverySignal]:
        max_per_language = max(
            1,
            min(
                4,
                int(
                    os.getenv(
                        "CONTENT_FACTORY_MAX_CANDIDATES_PER_LANGUAGE",
                        str(
                            load_language_market_config()[
                                "scoring"
                            ][
                                "max_candidates_per_language"
                            ]
                        ),
                    )
                ),
            ),
        )

        selected: list[
            DiscoverySignal
        ] = []
        counts: dict[
            str,
            int,
        ] = {}

        for candidate in candidates:
            language = (
                candidate.language_code
                or "unknown"
            )

            if counts.get(
                language,
                0,
            ) >= max_per_language:
                continue

            selected.append(
                candidate
            )
            counts[
                language
            ] = (
                counts.get(
                    language,
                    0,
                )
                + 1
            )

            if len(
                selected
            ) >= budget:
                return selected

        # If language caps leave unused slots, fill by raw score.
        seen = {
            id(item)
            for item in selected
        }

        for candidate in candidates:
            if id(
                candidate
            ) in seen:
                continue

            selected.append(
                candidate
            )

            if len(
                selected
            ) >= budget:
                break

        return selected

    async def _topics_from_real_headlines(
        self,
        news: list[str],
        hn: list[str],
    ) -> list[str]:
        source_lines = [
            *[f"[Google News] {x}" for x in news[:20]],
            *[f"[Hacker News] {x}" for x in hn[:20]],
        ]

        if not source_lines:
            return []

        prompt = f"""
Convert these REAL current headlines into at most 8 concise searchable topics.

SOURCE HEADLINES
{chr(10).join(source_lines)}

RULES
1. Every output topic MUST be clearly grounded in one or more headlines above.
2. Do not invent a topic not present in the source headlines.
3. Use 2 to 7 words per topic.
4. Merge duplicate headlines about the same event/topic.
5. Do not output vague words like "news", "teacher", "SEC", or "update"
   without enough context.
6. Return only the ResearchPlan JSON schema.
"""

        try:
            plan = await self._llm.generate_structured(
                prompt,
                ResearchPlan,
                system_prompt=(
                    "Extract topics only from supplied real headlines. "
                    "Never invent trends."
                ),
            )
        except Exception:
            return []

        seen: set[str] = set()
        result: list[str] = []

        for item in plan.topics:
            topic = self._clean_topic(str(item))
            if (
                topic
                and topic.lower() not in AUTO_SENTINELS
                and topic.lower() not in seen
            ):
                seen.add(topic.lower())
                result.append(topic)

        return result[:8]

    @classmethod
    def _clean_topic(cls, raw: str) -> str:
        text = re.sub(
            r"\s+",
            " ",
            raw.replace("|", " ").replace("–", " ").replace("—", " "),
        ).strip(" -:;,.'\"")

        if not text:
            return ""

        words = text.split()

        while len(words) > 1:
            last = re.sub(r"[^a-z0-9]", "", words[-1].lower())
            if last in PUBLISHER_SUFFIXES:
                words.pop()
            else:
                break

        cleaned_words: list[str] = []
        for word in words:
            bare = re.sub(r"[^a-z0-9]", "", word.lower())
            if bare in SPECIAL_CASE:
                cleaned_words.append(SPECIAL_CASE[bare])
            elif word.islower():
                cleaned_words.append(word.capitalize())
            else:
                cleaned_words.append(word)

        return " ".join(cleaned_words).strip()

    @classmethod
    def _topic_clarity(
        cls,
        topic: str,
    ) -> float:
        if is_calendar_only_topic(
            topic
        ):
            return 20.0

        raw_tokens = unicode_tokens(
            topic,
            min_length=1,
        )

        if not raw_tokens:
            return 0.0

        if len(raw_tokens) == 1:
            token = raw_tokens[0]

            if (
                token in GENERIC_ONE_WORD_TOPICS
                or len(token) <= 3
            ):
                score = 20.0
            else:
                score = 68.0

        elif len(raw_tokens) == 2:
            score = 92.0

        elif len(raw_tokens) <= 6:
            score = 100.0

        elif len(raw_tokens) <= 9:
            score = 80.0

        else:
            score = 60.0

        generic_count = sum(
            1
            for token in raw_tokens
            if token in GENERIC_ONE_WORD_TOPICS
        )

        score -= min(
            25.0,
            generic_count * 10.0,
        )

        return max(
            0.0,
            min(
                score,
                100.0,
            ),
        )

    @staticmethod
    def _parse_traffic(text: str) -> int:
        normalized = (
            text.upper().replace(",", "").replace("+", "").strip()
        )
        match = re.search(r"([\d.]+)\s*([KMB]?)", normalized)
        if not match:
            return 0

        value = float(match.group(1))
        suffix = match.group(2)
        multiplier = {
            "": 1,
            "K": 1_000,
            "M": 1_000_000,
            "B": 1_000_000_000,
        }.get(suffix, 1)

        return int(value * multiplier)

    @staticmethod
    def _tokens(
        text: str,
    ) -> set[str]:
        return {
            token
            for token in unicode_tokens(
                text,
                min_length=2,
            )
            if token not in STOP_WORDS
        }

    @classmethod
    def _match_count(cls, topic: str, texts: list[str]) -> int:
        topic_tokens = cls._tokens(topic)
        if not topic_tokens:
            return 0

        count = 0
        for text in texts:
            tokens = cls._tokens(text)
            overlap = len(topic_tokens & tokens)

            if len(topic_tokens) == 1:
                matched = overlap == 1
            else:
                matched = (overlap / len(topic_tokens)) >= 0.50

            if matched:
                count += 1

        return count
