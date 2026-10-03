from __future__ import annotations

import os
from datetime import datetime, timezone

from content_factory.agents.base import Agent
from content_factory.llm.base import LLMProvider
from content_factory.models.content import ScriptReview, YouTubeScript
from content_factory.modes import is_study_mode
from content_factory.orchestration.state import WorkflowState
from content_factory.utils.study_script_quality import study_script_quality_report


class ScriptReviewerAgent(Agent):
    """Review and self-repair study scripts before factual approval/rendering.

    The LLM review remains useful, but deterministic coherence checks are a hard
    companion gate. A low-scoring/repetitive script must not continue merely
    because an auto-approval workflow is enabled.
    """

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    @property
    def name(self) -> str:
        return "Script Reviewer Agent"

    async def execute(self, state: WorkflowState) -> WorkflowState:
        if state.script is None:
            raise ValueError("YouTube script is required before review.")

        if is_study_mode(state):
            await self._retry_primary("quality-critical script review")

        review = await self._review(state)
        deterministic = study_script_quality_report(state.script)
        state.metadata["study_script_quality"] = deterministic

        minimum = float(os.getenv("STUDY_SCRIPT_MIN_REVIEW_SCORE", "80"))
        structure_min = float(os.getenv("STUDY_SCRIPT_MIN_STRUCTURE_SCORE", "78"))
        audience_min = float(os.getenv("STUDY_SCRIPT_MIN_AUDIENCE_SCORE", "78"))

        needs_repair = is_study_mode(state) and (
            not bool(deterministic["passed"])
            or not review.approved
            or review.score < minimum
            or review.structure_quality < structure_min
            or review.audience_fit < audience_min
        )

        if needs_repair:
            print(
                "[REVIEW GATE] study script requires one coherence repair: "
                f"llm={review.score:.1f} deterministic={deterministic['score']:.1f} "
                f"issues={deterministic['issues'][:3]}"
            )
            await self._retry_primary("study script coherence repair")
            candidate = await self._repair_study_script(state, review, deterministic)
            candidate_report = study_script_quality_report(candidate)
            # Never replace the script with a deterministically worse candidate.
            if float(candidate_report["score"]) >= float(deterministic["score"]):
                state.script = candidate
                deterministic = candidate_report
                state.metadata["study_script_quality"] = deterministic
                review = await self._review(state)
                print(
                    "[REVIEW REPAIR] "
                    f"llm={review.score:.1f} deterministic={deterministic['score']:.1f}"
                )

        if is_study_mode(state):
            hard_fail = (
                not bool(deterministic["passed"])
                or not review.approved
                or review.score < minimum
                or review.structure_quality < structure_min
                or review.audience_fit < audience_min
            )
            if hard_fail:
                raise RuntimeError(
                    "Study script quality gate failed after one repair; refusing to spend "
                    "voice/render time on a repetitive or incoherent lesson. "
                    f"review={review.score:.1f} structure={review.structure_quality:.1f} "
                    f"audience={review.audience_fit:.1f} deterministic={deterministic['score']:.1f} "
                    f"issues={deterministic['issues'][:4]}"
                )

        state.script_review = review
        state.status = "script_reviewed"
        self._print_review(review)
        return state

    async def _retry_primary(self, reason: str) -> None:
        retry = getattr(self._llm, "retry_primary", None)
        if callable(retry):
            try:
                await retry(reason)
            except Exception as exc:
                print(f"[REVIEW GATE] primary retry skipped ({exc.__class__.__name__})")

    async def _review(self, state: WorkflowState) -> ScriptReview:
        assert state.script is not None
        current_date = datetime.now(timezone.utc).date().isoformat()
        prompt = f"""
You are a strict YouTube script reviewer.

CURRENT DATE
{current_date}

TOPIC
{state.topic or "unknown"}

USER-REQUESTED SCOPE
{state.metadata.get("requested_topic", state.topic or "unknown")}

TARGET LANGUAGE
{state.metadata.get("target_language_name", "unknown")}

SCRIPT
{state.script.model_dump_json(indent=2)}

COMPACT CURRENT EVIDENCE
{self._evidence_context(state)}

Review from 0 to 100 for:
- overall score
- factual_quality
- structure_quality
- audience_fit

IMPORTANT RULES
1. Judge factual consistency only against supplied evidence/stable technical knowledge as appropriate.
2. Penalize vague, generic and repetitive writing heavily.
3. Placeholder headings such as "Part 3" or "Section 2" are production defects.
4. Repeating the same safety/example paragraph across sections is a production defect even when factually true.
5. A strong technical lesson should progress: learner problem -> mental model -> worked mechanism -> implementation/detail -> verification -> edge cases/tradeoffs -> concise recap/practice.
6. If USER-REQUESTED SCOPE explicitly names facets, penalize silently dropping them.
7. Penalize code that is repeated unchanged across multiple scenes/sections or is not connected to the mechanism being taught.
8. Keep issues concise/actionable; max 5 issues and 5 recommendations.
9. Set approved=true only when the script is genuinely suitable for voice/render production, not merely fact-checkable.
10. Return only valid JSON.
"""
        return await self._llm.generate_structured(
            prompt=prompt,
            response_model=ScriptReview,
            system_prompt=(
                "Act as a production gate for educational YouTube. A technically true but "
                "repetitive/confusing script is not approved."
            ),
        )

    async def _repair_study_script(
        self,
        state: WorkflowState,
        review: ScriptReview,
        deterministic: dict[str, object],
    ) -> YouTubeScript:
        assert state.script is not None
        prompt = f"""
Repair this educational YouTube script ONCE for coherence and teaching quality.

TOPIC
{state.topic or "unknown"}

USER-REQUESTED SCOPE
{state.metadata.get("requested_topic", state.topic or "unknown")}

CURRENT SCRIPT
{state.script.model_dump_json(indent=2)}

REVIEW ISSUES
{review.model_dump_json(indent=2)}

DETERMINISTIC QUALITY ISSUES
{deterministic.get("issues", [])}

STRICT REPAIR CONTRACT
1. Preserve the core factual meaning; do not add time-sensitive claims, current weather/prices, dates, statistics, quotes or unsupported product facts.
2. For stable technical concepts explicitly requested by the topic, you may restore omitted teaching facets using established technical fundamentals; Fact Checker runs after this repair.
3. Replace placeholder headings (Part/Section/Chapter N) with topic-specific headings.
4. Remove duplicated boilerplate/examples. Each section needs a distinct teaching job and a distinct worked example only when useful.
5. Maintain one continuous mental model: goal -> decision/plan -> tool/action -> observation -> next decision -> completion for agent topics.
6. Code must correspond to the mechanism just taught; do not repeat one generic parse/validate/execute snippet across sections.
7. Verification content should vary by failure mode (wrong tool, invalid args, loop/no progress, permission boundary, incomplete completion) rather than repeating ALLOW/BLOCK.
8. Preserve approximately the same total duration and target language.
9. Keep the opening concise and the conclusion/CTA natural.
10. Return only YouTubeScript JSON.
"""
        candidate = await self._llm.generate_structured(
            prompt,
            YouTubeScript,
            system_prompt=(
                "You are a senior educational script editor. Repair coherence, repetition and "
                "teaching sequence without inventing current facts."
            ),
        )
        # Packaging already ran before this gate; preserve the selected public title
        # and requested duration while repairing only narration structure/content.
        candidate.title = state.script.title
        candidate.estimated_duration_minutes = state.script.estimated_duration_minutes
        return candidate

    @staticmethod
    def _print_review(review: ScriptReview) -> None:
        print(
            "[REVIEW] "
            f"score={review.score}, factual={review.factual_quality}, "
            f"structure={review.structure_quality}, audience={review.audience_fit}, "
            f"issues={len(review.issues)}"
        )

    @staticmethod
    def _evidence_context(state: WorkflowState) -> str:
        lines: list[str] = []
        if state.research is not None and state.research.top_candidate is not None:
            for index, item in enumerate(state.research.top_candidate.evidence[:8], start=1):
                lines.append(f"YouTube {index}: {item.title} | uploaded={item.published_at or 'unknown'}")
        for index, item in enumerate(state.metadata.get("enriched_evidence", [])[:10], start=1):
            lines.append(
                f"News {index}: {item.get('title', '')} | source={item.get('source', '') or 'unknown'} | "
                f"published={item.get('published_at', '') or 'unknown'}"
            )
        grounding = state.metadata.get("topic_grounding", {})
        keywords = grounding.get("top_keywords", [])
        if keywords:
            lines.append("Grounding keywords: " + ", ".join(str(item) for item in keywords[:12]))
        return "\n".join(lines) if lines else "No current evidence supplied."
