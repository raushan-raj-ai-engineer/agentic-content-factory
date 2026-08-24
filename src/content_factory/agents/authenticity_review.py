from __future__ import annotations

import json
import re
from pathlib import Path

from content_factory.agents.base import Agent
from content_factory.llm.base import LLMProvider
from content_factory.models.content import YouTubeScript
from content_factory.orchestration.state import WorkflowState


STOP_WORDS = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for",
    "with", "this", "that", "is", "are", "was", "were", "be", "been",
    "it", "its", "we", "you", "your", "our", "from", "as", "at", "by",
    "today", "video", "let", "lets", "going", "look", "talk", "about",
}

GENERIC_SECTION_TITLES = {
    "introduction",
    "background",
    "overview",
    "what happened",
    "why it matters",
    "impact",
    "community reaction",
    "future",
    "the future",
    "conclusion",
    "final thoughts",
}


class AuthenticityReviewAgent(Agent):
    """
    Reduce mass-produced/template feel before Script Reviewer + Fact Checker.

    This agent is deliberately before factual review. If it reorganizes a
    generic script, the normal Script Reviewer and Fact Checker still run next.
    """

    def __init__(
        self,
        llm: LLMProvider,
        *,
        artifact_root: str = "artifacts",
    ) -> None:
        self._llm = llm
        self._artifact_root = Path(artifact_root)

    @property
    def name(self) -> str:
        return "Authenticity Review Agent"

    async def execute(
        self,
        state: WorkflowState,
    ) -> WorkflowState:
        if state.script is None:
            raise ValueError(
                "Script is required before authenticity review."
            )

        current = self._measure(state.script)
        prior_similarity = self._prior_similarity(
            state.topic or "",
            current["signature_tokens"],
        )

        risk, reasons = self._risk(
            current,
            prior_similarity,
        )

        state.metadata["authenticity_review"] = {
            "before_risk": risk,
            "before_reasons": reasons,
            "prior_similarity": round(
                prior_similarity,
                3,
            ),
        }

        if risk == "LOW":
            print(
                "[AUTHENTICITY] LOW risk — script structure is sufficiently "
                "topic-specific."
            )
            state.status = "authenticity_reviewed"
            return state

        print(
            f"[AUTHENTICITY] {risk} risk — "
            f"{'; '.join(reasons)}"
        )
        print(
            "[AUTHENTICITY] Reworking structure once before normal "
            "script/fact review."
        )

        prompt = f"""
Rewrite this YouTube script so it feels purpose-built for THIS topic rather
than produced from a reusable mass-production template.

TOPIC
{state.topic or "unknown"}

CURRENT SCRIPT
{state.script.model_dump_json(indent=2)}

CURRENT AUTHENTICITY ISSUES
{json.dumps(reasons, ensure_ascii=False, indent=2)}

STRICT RULES
1. Preserve every factual claim exactly in meaning. Do not add a new date,
   name, number, quote, source, company response, event, statistic, cause,
   or factual detail.
2. Do not delete important factual qualifications such as "reported",
   "alleged", "according to", or "unconfirmed".
3. Make section titles specific to the current topic instead of generic labels
   like Background, Impact, Future, or Final Thoughts.
4. Use a topic-specific narrative arc: a concrete question, tension, sequence,
   comparison, myth-vs-evidence, timeline, or explanatory journey that actually
   fits this subject.
5. Avoid repeated filler phrases commonly reused across videos.
6. Keep approximately the same narration length.
7. Keep the same narration language.
8. Do not invent dialogue for real people.
9. Do not create a numbered "Conclusion" section and then another conclusion.
10. Return only the YouTubeScript JSON schema.
"""

        repaired = await self._llm.generate_structured(
            prompt,
            YouTubeScript,
            system_prompt=(
                "Improve originality and structure only. "
                "Do not invent or alter factual claims."
            ),
        )

        after = self._measure(repaired)
        after_similarity = self._prior_similarity(
            state.topic or "",
            after["signature_tokens"],
        )
        after_risk, after_reasons = self._risk(
            after,
            after_similarity,
        )

        # Keep repaired version when it is no worse than the original.
        rank = {
            "LOW": 0,
            "MEDIUM": 1,
            "HIGH": 2,
        }

        if rank[after_risk] <= rank[risk]:
            state.script = repaired
            final_risk = after_risk
            final_reasons = after_reasons
            final_similarity = after_similarity
        else:
            final_risk = risk
            final_reasons = reasons
            final_similarity = prior_similarity

        state.metadata["authenticity_review"].update(
            {
                "final_risk": final_risk,
                "final_reasons": final_reasons,
                "final_prior_similarity": round(
                    final_similarity,
                    3,
                ),
            }
        )

        print(
            f"[AUTHENTICITY] Final risk: {final_risk}"
        )

        state.status = "authenticity_reviewed"
        return state

    def _prior_similarity(
        self,
        topic: str,
        current_tokens: list[str],
    ) -> float:
        current = set(current_tokens)

        if not current or not self._artifact_root.exists():
            return 0.0

        best = 0.0

        for report_path in self._artifact_root.rglob(
            "monetization_report.json"
        ):
            try:
                report = json.loads(
                    report_path.read_text(
                        encoding="utf-8"
                    )
                )
            except Exception:
                continue

            prior_topic = str(
                report.get("topic")
                or ""
            )

            if (
                prior_topic.strip().lower()
                == topic.strip().lower()
            ):
                # Same-topic reruns should not make a new version impossible.
                continue

            tokens = set(
                report.get("authenticity", {}).get(
                    "signature_tokens",
                    [],
                )
            )

            if not tokens:
                continue

            union = current | tokens
            if not union:
                continue

            score = len(
                current & tokens
            ) / len(union)

            best = max(
                best,
                score,
            )

        return best

    @classmethod
    def _measure(
        cls,
        script: YouTubeScript,
    ) -> dict[str, object]:
        titles = [
            section.title.strip()
            for section in script.sections
        ]
        normalized_titles = [
            cls._normalize(title)
            for title in titles
        ]

        generic_count = sum(
            1
            for title in normalized_titles
            if title in GENERIC_SECTION_TITLES
        )

        conclusion_sections = sum(
            1
            for title in normalized_titles
            if "conclusion" in title
            or "final thought" in title
        )

        narration = " ".join(
            [
                script.hook,
                script.introduction,
                *(
                    section.content
                    for section in script.sections
                ),
                script.conclusion,
                script.call_to_action,
            ]
        )

        tokens = cls._signature_tokens(
            narration
        )

        word_count = len(
            re.findall(
                r"\b[\w@./+-]+\b",
                narration,
                flags=re.UNICODE,
            )
        )

        return {
            "section_count": len(titles),
            "generic_section_count": generic_count,
            "conclusion_sections": conclusion_sections,
            "signature_tokens": tokens,
            "word_count": word_count,
        }

    @staticmethod
    def _risk(
        metrics: dict[str, object],
        prior_similarity: float,
    ) -> tuple[str, list[str]]:
        reasons: list[str] = []

        section_count = int(
            metrics["section_count"]
        )
        generic_count = int(
            metrics["generic_section_count"]
        )
        conclusion_sections = int(
            metrics["conclusion_sections"]
        )

        if section_count >= 4:
            ratio = generic_count / section_count
        else:
            ratio = 0.0

        if ratio >= 0.60:
            reasons.append(
                "most section titles are generic/reusable"
            )

        if conclusion_sections >= 1:
            reasons.append(
                "a conclusion/final-thoughts section duplicates the dedicated conclusion"
            )

        if prior_similarity >= 0.72:
            reasons.append(
                f"script signature is highly similar to a prior different-topic run "
                f"({prior_similarity:.2f})"
            )

        if (
            prior_similarity >= 0.82
            or ratio >= 0.80
        ):
            return "HIGH", reasons

        if reasons:
            return "MEDIUM", reasons

        return "LOW", []

    @staticmethod
    def _signature_tokens(
        text: str,
    ) -> list[str]:
        words = [
            token.lower()
            for token in re.findall(
                r"[A-Za-zÀ-ÿ\u0900-\u097F\u0400-\u04FF]{3,}",
                text,
            )
        ]

        counts: dict[str, int] = {}

        for word in words:
            if word in STOP_WORDS:
                continue
            counts[word] = counts.get(
                word,
                0,
            ) + 1

        # Stable set-like signature with enough information for future runs.
        ranked = sorted(
            counts.items(),
            key=lambda pair: (
                -pair[1],
                pair[0],
            ),
        )

        return [
            word
            for word, _ in ranked[:180]
        ]

    @staticmethod
    def _normalize(
        text: str,
    ) -> str:
        return re.sub(
            r"\s+",
            " ",
            re.sub(
                r"[^a-z0-9 ]+",
                " ",
                text.lower(),
            ),
        ).strip()
