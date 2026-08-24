from __future__ import annotations

from datetime import datetime, timezone

from content_factory.agents.base import Agent
from content_factory.llm.base import LLMProvider
from content_factory.models.content import ScriptReview
from content_factory.orchestration.state import WorkflowState


class ScriptReviewerAgent(Agent):
    """
    Review structure/audience quality with compact factual context.

    Fact Checker remains the authoritative factual gate; this reviewer must not
    invent factual objections from model memory.
    """

    def __init__(
        self,
        llm: LLMProvider,
    ) -> None:
        self._llm = llm

    @property
    def name(self) -> str:
        return "Script Reviewer Agent"

    async def execute(
        self,
        state: WorkflowState,
    ) -> WorkflowState:
        if state.script is None:
            raise ValueError(
                "YouTube script is required before review."
            )

        script_json = state.script.model_dump_json(
            indent=2
        )

        current_date = datetime.now(
            timezone.utc
        ).date().isoformat()

        prompt = f"""
You are a strict YouTube script reviewer.

CURRENT DATE
{current_date}

TOPIC
{state.topic or "unknown"}

TARGET LANGUAGE
{state.metadata.get("target_language_name", "unknown")}

SCRIPT
{script_json}

COMPACT CURRENT EVIDENCE
{self._evidence_context(state)}

Review from 0 to 100 for:
- overall score
- factual_quality
- structure_quality
- audience_fit

IMPORTANT FACTUAL REVIEW RULES
1. Judge factual consistency ONLY against the supplied current evidence.
2. Do not use stale model knowledge to say a 2026 event "may not exist".
3. If evidence supports a named event/person/date, do not flag it merely
   because you personally cannot verify it from memory.
4. If evidence is insufficient, phrase the issue as "Fact Checker should
   verify X" rather than declaring X false.
5. Fact Checker is the authoritative factual gate after this review.
6. Penalize vague/generic/repetitive writing, language mixing, poor structure,
   weak audience fit and unsupported certainty visible from the evidence.
7. Keep issues concise and actionable.
8. Return at most 5 issues and at most 5 recommendations.
9. Set approved=true when the script is suitable to continue to Fact Checker.

Return recommendations as objects with:
- id
- action

Return ONLY valid JSON.
"""

        review = await self._llm.generate_structured(
            prompt=prompt,
            response_model=ScriptReview,
            system_prompt=(
                "Review only against supplied script/evidence. "
                "Do not invent factual conflicts from memory."
            ),
        )

        state.script_review = review
        state.status = "script_reviewed"

        print(
            "[REVIEW] "
            f"score={review.score}, "
            f"factual={review.factual_quality}, "
            f"structure={review.structure_quality}, "
            f"audience={review.audience_fit}, "
            f"issues={len(review.issues)}"
        )

        return state

    @staticmethod
    def _evidence_context(
        state: WorkflowState,
    ) -> str:
        lines: list[str] = []

        if (
            state.research is not None
            and state.research.top_candidate is not None
        ):
            for index, item in enumerate(
                state.research.top_candidate.evidence[:8],
                start=1,
            ):
                lines.append(
                    f"YouTube {index}: {item.title} | "
                    f"uploaded={item.published_at or 'unknown'}"
                )

        enriched = state.metadata.get(
            "enriched_evidence",
            [],
        )

        for index, item in enumerate(
            enriched[:10],
            start=1,
        ):
            lines.append(
                f"News {index}: {item.get('title', '')} | "
                f"source={item.get('source', '') or 'unknown'} | "
                f"published={item.get('published_at', '') or 'unknown'}"
            )

        grounding = state.metadata.get(
            "topic_grounding",
            {},
        )

        keywords = grounding.get(
            "top_keywords",
            [],
        )

        if keywords:
            lines.append(
                "Grounding keywords: "
                + ", ".join(
                    str(item)
                    for item in keywords[:12]
                )
            )

        return (
            "\n".join(
                lines
            )
            if lines
            else "No current evidence supplied."
        )
