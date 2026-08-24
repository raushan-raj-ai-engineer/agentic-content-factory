from __future__ import annotations

import asyncio
import math
import re
from datetime import datetime, timedelta, timezone

from content_factory.agents.base import Agent
from content_factory.models.content import (
    ResearchEvidence,
    TrendCandidate,
    TrendResearch,
)
from content_factory.orchestration.state import WorkflowState
from content_factory.research.base import ResearchService
from content_factory.research.trend_signals import get_signal
from content_factory.research.language_market import (
    load_language_market_config,
    market_factor,
    target_locale,
)
from content_factory.research.topic_quality import (
    is_calendar_only_topic,
    topic_quality_factor,
)
from content_factory.utils.unicode_tokens import (
    unicode_token_set,
    unicode_tokens,
)


STOP_WORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for",
    "with", "from", "at", "by", "is", "are", "was", "were", "be",
    "this", "that", "as", "it", "its", "new", "latest", "today",
    "video", "videos", "live",
}

GENERIC_ONE_WORD_TOPICS = {
    "sec", "teacher", "news", "live", "update", "result", "results",
    "match", "weather", "video", "viral", "trend", "trending", "breaking",
    "ന്യൂസ്", "समाचार", "खबर", "अपडेट", "செய்திகள்", "செய்தி",
    "ಸುದ್ದಿ", "સમાચાર", "খবর", "সংবাদ",
}


class TrendResearchAgent(Agent):
    """Validate real trends with relevant YouTube evidence and safer scoring."""

    def __init__(
        self,
        research_service: ResearchService,
        *,
        lookback_days: int = 7,
    ) -> None:
        self._research_service = research_service
        self._lookback_days = max(1, lookback_days)

    @property
    def name(self) -> str:
        return "Trend Research Agent"

    async def execute(
        self,
        state: WorkflowState,
    ) -> WorkflowState:
        if state.research_plan is None:
            raise ValueError(
                "Research plan is required."
            )

        topics = list(
            state.research_plan.topics
        )

        if not topics:
            state.status = "no_research_results"
            raise RuntimeError(
                "No research topics were provided."
            )

        # Network/subprocess searches are independent. Run a small number in
        # parallel so quality/scoring stays identical without waiting for all
        # candidates serially.
        concurrency = max(
            1,
            min(
                5,
                int(
                    __import__("os").getenv(
                        "CONTENT_FACTORY_TREND_CONCURRENCY",
                        "4",
                    )
                ),
            ),
        )

        semaphore = asyncio.Semaphore(
            concurrency
        )

        candidate_timeout = max(
            20.0,
            min(
                90.0,
                float(
                    __import__("os").getenv(
                        "CONTENT_FACTORY_TREND_CANDIDATE_TIMEOUT",
                        "50",
                    )
                ),
            ),
        )

        print(
            f"[PERF] Trend validation concurrency={concurrency}, "
            f"candidate_timeout={candidate_timeout:.0f}s"
        )

        async def run_one(
            index: int,
            topic: str,
        ):
            async with semaphore:
                try:
                    candidate, log_line = await asyncio.wait_for(
                        self._research_topic(
                            topic
                        ),
                        timeout=candidate_timeout,
                    )
                except asyncio.TimeoutError:
                    raise TimeoutError(
                        f"trend candidate exceeded "
                        f"{candidate_timeout:.0f}s"
                    )

                return (
                    index,
                    candidate,
                    log_line,
                )

        results = await asyncio.gather(
            *[
                run_one(
                    index,
                    topic,
                )
                for index, topic
                in enumerate(
                    topics
                )
            ],
            return_exceptions=True,
        )

        ordered: list[
            tuple[
                int,
                TrendCandidate,
                str,
            ]
        ] = []

        for index, result in enumerate(
            results
        ):
            topic = topics[
                index
            ]

            if isinstance(
                result,
                Exception,
            ):
                if isinstance(
                    result,
                    TimeoutError,
                ):
                    print(
                        f"[TREND] {topic}: skipped after "
                        f"{candidate_timeout:.0f}s timeout"
                    )
                else:
                    print(
                        f"[TREND] {topic}: research failed "
                        f"({result.__class__.__name__})"
                    )
                continue

            ordered.append(
                result
            )

        ordered.sort(
            key=lambda item: item[0]
        )

        candidates: list[
            TrendCandidate
        ] = []

        for _, candidate, log_line in ordered:
            candidates.append(
                candidate
            )
            print(
                log_line
            )

        if not candidates:
            state.status = "no_research_results"
            raise RuntimeError(
                "No usable research candidates were found."
            )

        candidates.sort(
            key=lambda item: item.opportunity_score,
            reverse=True,
        )

        state.research = TrendResearch(
            candidates=candidates,
            top_candidate=candidates[0],
        )
        state.topic = candidates[
            0
        ].topic

        selected_signal = get_signal(
            state.topic
        )

        if (
            selected_signal
            is not None
            and hasattr(
                state,
                "metadata",
            )
        ):
            state.metadata[
                "target_language"
            ] = selected_signal.language_code
            state.metadata[
                "target_language_name"
            ] = selected_signal.language_name
            state.metadata[
                "target_market_geo"
            ] = selected_signal.market_geo
            state.metadata[
                "target_market_name"
            ] = selected_signal.market_name
            state.metadata[
                "language_priority"
            ] = selected_signal.language_priority

            resolved_locale = target_locale(
                selected_signal.language_code,
                selected_signal.market_geo,
            )

            state.metadata[
                "target_locale"
            ] = resolved_locale

            print(
                "[MARKET] Selected "
                f"language={selected_signal.language_code}/"
                f"{selected_signal.language_name}, "
                f"market={selected_signal.market_geo}/"
                f"{selected_signal.market_name}, "
                f"locale={resolved_locale}, "
                f"priority={selected_signal.language_priority:.2f}"
            )

        state.status = "researched"

        print(
            "[TREND] Ranking:"
        )

        for index, candidate in enumerate(
            candidates[
                :5
            ],
            start=1,
        ):
            print(
                f"[TREND] #{index} {candidate.topic}: "
                f"{candidate.opportunity_score}"
            )

        print(
            f"[TREND] Selected topic: {state.topic}"
        )

        return state

    async def _research_topic(
        self,
        topic: str,
    ) -> tuple[
        TrendCandidate,
        str,
    ]:
        evidence = await self._research_service.search(
            topic
        )

        relevant_evidence = [
            item
            for item in evidence
            if self._evidence_relevance(
                topic,
                item.title,
            )
            >= self._relevance_threshold(
                topic
            )
        ]

        recent_all = self._recent_evidence(
            evidence
        )
        recent = self._recent_evidence(
            relevant_evidence
        )

        prefix = ""

        if not recent:
            prefix = (
                f"[TREND] {topic}: no fresh relevant YouTube evidence "
                f"inside {self._lookback_days} days\n"
            )

        relevance_ratio = (
            len(
                recent
            )
            / len(
                recent_all
            )
            if recent_all
            else 0.0
        )

        mean_relevance = self._mean_relevance(
            topic,
            recent,
        )

        youtube_trend = self._calculate_trend_score(
            recent
        )
        competition = self._calculate_competition(
            recent
        )
        confidence = self._trend_confidence(
            recent
        )

        youtube_opportunity = 0.0

        if recent:
            youtube_opportunity = (
                (
                    youtube_trend
                    * 0.62
                )
                + (
                    (
                        100
                        - competition
                    )
                    * 0.13
                )
                + (
                    mean_relevance
                    * 100
                    * 0.15
                )
                + (
                    min(
                        len(
                            recent
                        )
                        / 5.0,
                        1.0,
                    )
                    * 100
                    * 0.10
                )
            ) * confidence

        discovery_signal = get_signal(
            topic
        )

        discovery_score = (
            discovery_signal.score
            if discovery_signal
            is not None
            else 0.0
        )

        clarity = (
            discovery_signal.clarity_score
            if discovery_signal
            is not None
            else self._topic_clarity(
                topic
            )
        )

        video_worthiness = (
            self._video_worthiness(
                clarity=clarity,
                youtube_trend=youtube_trend,
                youtube_confidence=confidence,
                relevance=mean_relevance,
                sample_size=len(
                    recent
                ),
            )
        )

        quality_factor, evidence_coherence = topic_quality_factor(
            topic,
            [
                item.title
                for item in recent
            ],
        )

        if discovery_signal is not None:
            if recent:
                base_score = (
                    discovery_score
                    * 0.45
                    + youtube_opportunity
                    * 0.35
                    + video_worthiness
                    * 0.20
                )
            else:
                base_score = (
                    discovery_score
                    * 0.60
                    + video_worthiness
                    * 0.15
                )

            source_count = len(
                set(
                    discovery_signal.sources
                )
            )

            if recent:
                source_count += 1

            cross_source_factor = (
                self._cross_source_factor(
                    source_count
                )
            )

            ambiguity_factor = (
                self._ambiguity_factor(
                    topic,
                    clarity,
                )
            )

            language_share = float(
                load_language_market_config()[
                    "scoring"
                ][
                    "trend_final_language_share"
                ]
            )

            language_factor = market_factor(
                discovery_signal.language_priority,
                share=language_share,
            )

            final_opportunity = (
                base_score
                * cross_source_factor
                * ambiguity_factor
                * language_factor
                * quality_factor
            )

        else:
            source_count = (
                1
                if recent
                else 0
            )
            cross_source_factor = 1.0
            language_factor = 1.0

            final_opportunity = (
                youtube_opportunity
                * 0.80
                + video_worthiness
                * 0.20
            ) * quality_factor

        candidate = TrendCandidate(
            topic=topic,
            trend_score=youtube_trend,
            audience_fit=max(
                0,
                min(
                    100,
                    round(
                        video_worthiness
                    ),
                ),
            ),
            competition=competition,
            opportunity_score=round(
                max(
                    0.0,
                    min(
                        final_opportunity,
                        100.0,
                    ),
                ),
                2,
            ),
            evidence=relevant_evidence,
        )

        source_text = "-"

        if discovery_signal is not None:
            source_text = ",".join(
                discovery_signal.sources
            )

        log_line = (
            prefix
            + f"[TREND] {topic}: "
            f"discovery={discovery_score:.1f}, "
            f"clarity={clarity:.0f}, "
            f"youtube={youtube_trend}, "
            f"yt_recent={len(recent)}/{len(recent_all)}, "
            f"yt_relevance={relevance_ratio:.2f}, "
            f"yt_confidence={confidence:.2f}, "
            f"video_score={video_worthiness:.1f}, "
            f"sources={source_count}, "
            f"cross={cross_source_factor:.2f}, "
            f"lang={(
                discovery_signal.language_code
                if discovery_signal
                else '-'
            )}, "
            f"lang_priority={(
                discovery_signal.language_priority
                if discovery_signal
                else 0.0
            ):.2f}, "
            f"market_factor={language_factor:.3f}, "
            f"coherence={evidence_coherence:.2f}, "
            f"topic_quality={quality_factor:.2f}, "
            f"competition={competition}, "
            f"final={candidate.opportunity_score}, "
            f"discovery_sources={source_text}"
        )

        return (
            candidate,
            log_line,
        )

    def _recent_evidence(
        self,
        evidence: list[ResearchEvidence],
    ) -> list[ResearchEvidence]:
        cutoff = (
            datetime.now(timezone.utc)
            - timedelta(days=self._lookback_days)
        )
        result: list[ResearchEvidence] = []

        for item in evidence:
            published = self._parse_datetime(item.published_at)
            if published is not None and published >= cutoff:
                result.append(item)

        return result

    def _calculate_trend_score(
        self,
        evidence: list[ResearchEvidence],
    ) -> int:
        if not evidence:
            return 0

        lookback_hours = float(self._lookback_days * 24)
        scores: list[float] = []

        for item in evidence:
            published = self._parse_datetime(item.published_at)
            if published is None:
                continue

            age_hours = max(
                (
                    datetime.now(timezone.utc) - published
                ).total_seconds() / 3600.0,
                1.0,
            )

            views = max(item.view_count, 0)
            likes = max(item.like_count, 0)
            comments = max(item.comment_count, 0)

            views_per_hour = views / age_hours
            velocity = min(
                math.log10(views_per_hour + 1) / 4.0,
                1.0,
            )
            recency = max(
                0.0,
                1.0 - (age_hours / lookback_hours),
            )
            like_rate = likes / views if views else 0.0
            comment_rate = comments / views if views else 0.0

            score = (
                velocity * 0.50
                + recency * 0.30
                + min(like_rate / 0.08, 1.0) * 0.12
                + min(comment_rate / 0.02, 1.0) * 0.08
            )
            scores.append(score)

        if not scores:
            return 0

        scores.sort(reverse=True)
        top = scores[: min(5, len(scores))]
        return max(
            0,
            min(
                100,
                round((sum(top) / len(top)) * 100),
            ),
        )

    @staticmethod
    def _trend_confidence(
        evidence: list[ResearchEvidence],
    ) -> float:
        if not evidence:
            return 0.0

        sample_confidence = min(len(evidence) / 4.0, 1.0)
        total_views = sum(
            max(item.view_count, 0)
            for item in evidence
        )
        view_confidence = min(
            math.sqrt(total_views / 2_000.0),
            1.0,
        )

        return max(
            0.0,
            min(sample_confidence * view_confidence, 1.0),
        )

    @staticmethod
    def _calculate_competition(
        evidence: list[ResearchEvidence],
    ) -> int:
        if not evidence:
            return 0

        high_view = sum(
            1
            for item in evidence
            if item.view_count >= 100_000
        )

        return min(
            min(len(evidence) * 5, 50)
            + min(high_view * 10, 40),
            100,
        )

    @classmethod
    def _evidence_relevance(
        cls,
        topic: str,
        title: str,
    ) -> float:
        topic_tokens = cls._tokens(
            topic
        )
        title_tokens = cls._tokens(
            title
        )

        if (
            not topic_tokens
            or not title_tokens
        ):
            return 0.0

        normalized_topic = " ".join(
            unicode_tokens(
                topic,
                min_length=1,
            )
        )
        normalized_title = " ".join(
            unicode_tokens(
                title,
                min_length=1,
            )
        )

        if (
            normalized_topic
            and normalized_topic
            in normalized_title
        ):
            return 1.0

        overlap = len(
            topic_tokens
            & title_tokens
        )

        return min(
            1.0,
            overlap
            / len(topic_tokens),
        )

    @classmethod
    def _mean_relevance(
        cls,
        topic: str,
        evidence: list[ResearchEvidence],
    ) -> float:
        if not evidence:
            return 0.0

        values = [
            cls._evidence_relevance(topic, item.title)
            for item in evidence
        ]
        return sum(values) / len(values)

    @classmethod
    def _relevance_threshold(cls, topic: str) -> float:
        count = len(cls._tokens(topic))
        if count <= 1:
            return 1.0
        if count == 2:
            return 0.50
        return 0.45

    @staticmethod
    def _video_worthiness(
        *,
        clarity: float,
        youtube_trend: int,
        youtube_confidence: float,
        relevance: float,
        sample_size: int,
    ) -> float:
        demand = youtube_trend * youtube_confidence
        sample_score = min(sample_size / 5.0, 1.0) * 100.0

        return max(
            0.0,
            min(
                100.0,
                clarity * 0.30
                + demand * 0.35
                + relevance * 100.0 * 0.20
                + sample_score * 0.15,
            ),
        )

    @staticmethod
    def _cross_source_factor(source_count: int) -> float:
        if source_count <= 1:
            return 0.70
        if source_count == 2:
            return 0.90
        if source_count == 3:
            return 1.00
        return 1.05

    @classmethod
    def _ambiguity_factor(
        cls,
        topic: str,
        clarity: float,
    ) -> float:
        tokens = unicode_tokens(
            topic,
            min_length=1,
        )

        if len(tokens) == 1:
            token = tokens[0]

            if (
                token in GENERIC_ONE_WORD_TOPICS
                or len(token) <= 3
            ):
                return 0.20

            return 0.75

        if clarity < 50:
            return 0.55

        if clarity < 75:
            return 0.80

        return 1.0

    @classmethod
    def _topic_clarity(
        cls,
        topic: str,
    ) -> float:
        if is_calendar_only_topic(
            topic
        ):
            return 20.0

        tokens = unicode_tokens(
            topic,
            min_length=1,
        )

        if not tokens:
            return 0.0

        if len(tokens) == 1:
            token = tokens[0]

            if (
                token in GENERIC_ONE_WORD_TOPICS
                or len(token) <= 3
            ):
                return 20.0

            return 68.0

        if len(tokens) == 2:
            return 92.0

        if len(tokens) <= 6:
            return 100.0

        if len(tokens) <= 9:
            return 80.0

        return 60.0

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

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        if not value:
            return None

        try:
            parsed = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            return None
