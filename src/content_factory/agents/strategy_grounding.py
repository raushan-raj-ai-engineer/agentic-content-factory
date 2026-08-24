from __future__ import annotations

import re
from collections import Counter

from content_factory.agents.base import Agent
from content_factory.orchestration.state import WorkflowState
from content_factory.research.trend_signals import get_signal


STOP_WORDS = {
    "about", "after", "again", "against", "also", "and", "are", "around",
    "because", "been", "before", "being", "between", "bring", "brings",
    "could", "current", "deep", "does", "from", "have", "here", "into",
    "latest", "more", "movie", "film", "news", "over", "past", "review",
    "shapes", "story", "today", "understanding", "what", "when", "where",
    "which", "while", "with", "would", "your", "this", "that", "than",
    "their", "they", "them", "then", "there", "through", "will", "why",
    "youtube", "video", "viewers", "viewer", "explained", "update",
}

SAFE_WORDS = {
    "explained", "latest", "update", "review", "what", "know", "knows",
    "why", "how", "inside", "today", "movie", "film", "story", "details",
    "confirmed", "reports", "says", "say", "current", "new", "look",
}


class StrategyGroundingAgent(Agent):
    """Deterministically stop unsupported strategy/topic drift."""

    @property
    def name(self) -> str:
        return "Strategy Grounding Agent"

    async def execute(
        self,
        state: WorkflowState,
    ) -> WorkflowState:
        if state.strategy is None:
            raise ValueError(
                "Content strategy is required."
            )

        topic = (
            state.topic
            or state.strategy.topic
        ).strip()

        corpus = self._evidence_corpus(state)

        evidence_tokens = set(
            self._tokens(corpus)
        )
        topic_tokens = set(
            self._tokens(topic)
        )
        allowed = (
            evidence_tokens
            | topic_tokens
            | SAFE_WORDS
        )

        strategy_text = (
            f"{state.strategy.angle} "
            f"{state.strategy.hook}"
        )

        candidate_tokens = [
            token
            for token in self._tokens(strategy_text)
            if token not in STOP_WORDS
            and token not in topic_tokens
        ]

        unsupported = sorted(
            {
                token
                for token in candidate_tokens
                if token not in allowed
            }
        )

        keywords = self._top_keywords(
            state,
            topic,
        )

        evidence_count = self._evidence_count(
            state
        )

        duration_limit = self._duration_limit(
            evidence_count
        )

        original_duration = max(
            1,
            int(
                state.strategy.estimated_duration_minutes
            ),
        )

        target_duration = min(
            original_duration,
            duration_limit,
        )

        corrected = False

        if len(unsupported) >= 2:
            corrected = True

            keyword_phrase = ", ".join(
                keywords[:3]
            )

            if keyword_phrase:
                state.strategy.angle = (
                    f"What current public reports actually say about {topic}, "
                    f"with focus on {keyword_phrase}"
                )
            else:
                state.strategy.angle = (
                    f"What current public reports actually confirm about {topic}"
                )

            state.strategy.hook = (
                f"{topic} is trending. Here is what the current evidence "
                "actually confirms — without adding speculation."
            )

            print(
                "[GROUNDING] Strategy drift corrected. "
                f"Unsupported terms: {', '.join(unsupported[:8])}"
            )

        if target_duration < original_duration:
            state.strategy.estimated_duration_minutes = (
                target_duration
            )
            print(
                f"[GROUNDING] Evidence-based duration: "
                f"{original_duration}m -> {target_duration}m"
            )

        state.metadata["topic_grounding"] = {
            "topic": topic,
            "corrected": corrected,
            "unsupported_strategy_terms": unsupported[:20],
            "evidence_count": evidence_count,
            "top_keywords": keywords[:12],
            "target_duration_minutes": target_duration,
        }

        state.status = "strategy_grounded"
        return state

    @classmethod
    def _evidence_corpus(
        cls,
        state: WorkflowState,
    ) -> str:
        lines = []

        signal = get_signal(
            state.topic or ""
        )

        if signal is not None:
            lines.extend(
                signal.related_headlines[:15]
            )

        for item in state.metadata.get(
            "enriched_evidence",
            [],
        ):
            lines.append(
                str(item.get("title") or "")
            )
            lines.append(
                str(item.get("description") or "")
            )

        if state.research is not None:
            for item in (
                state.research.top_candidate.evidence[:16]
            ):
                lines.append(
                    item.title
                )

        return "\n".join(
            line
            for line in lines
            if line
        )

    @classmethod
    def _top_keywords(
        cls,
        state: WorkflowState,
        topic: str,
    ) -> list[str]:
        topic_tokens = set(
            cls._tokens(topic)
        )

        counts = Counter(
            token
            for token in cls._tokens(
                cls._evidence_corpus(state)
            )
            if token not in STOP_WORDS
            and token not in topic_tokens
            and len(token) >= 4
        )

        return [
            token
            for token, _
            in counts.most_common(20)
        ]

    @staticmethod
    def _tokens(value: str) -> list[str]:
        return [
            token.lower()
            for token in re.findall(
                r"[A-Za-zÀ-ÿ0-9]{3,}",
                value,
            )
        ]

    @staticmethod
    def _evidence_count(
        state: WorkflowState,
    ) -> int:
        titles = set()

        signal = get_signal(
            state.topic or ""
        )

        if signal is not None:
            titles.update(
                headline.lower()
                for headline in signal.related_headlines
                if headline
            )

        for item in state.metadata.get(
            "enriched_evidence",
            [],
        ):
            title = str(
                item.get("title") or ""
            ).strip()

            if title:
                titles.add(
                    title.lower()
                )

        if state.research is not None:
            titles.update(
                item.title.lower()
                for item in state.research.top_candidate.evidence
                if item.title
            )

        return len(titles)

    @staticmethod
    def _duration_limit(
        evidence_count: int,
    ) -> int:
        if evidence_count >= 18:
            return 7
        if evidence_count >= 12:
            return 6
        if evidence_count >= 8:
            return 5
        if evidence_count >= 5:
            return 4
        return 3
