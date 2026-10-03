from __future__ import annotations

import json
import re

from pydantic import BaseModel

from content_factory.agents.base import Agent
from content_factory.llm.base import LLMProvider
from content_factory.models.content import YouTubeScript
from content_factory.modes import is_study_mode
from content_factory.orchestration.state import WorkflowState


class OpeningRetention(BaseModel):
    hook: str
    introduction: str


class RetentionOptimizerAgent(Agent):
    """
    Optimize the highest-impact first ~30 seconds without regenerating the
    entire script.

    Body sections, conclusion and CTA remain byte-for-byte unchanged.
    This keeps factual quality stable and dramatically reduces generation time.
    """

    def __init__(
        self,
        llm: LLMProvider,
    ) -> None:
        self._llm = llm

    @property
    def name(
        self,
    ) -> str:
        return "Retention Optimizer Agent"

    async def execute(
        self,
        state: WorkflowState,
    ) -> WorkflowState:
        if state.script is None:
            raise ValueError(
                "Script is required before retention optimization."
            )

        script = state.script
        before = self._metrics(
            script
        )

        growth = state.metadata.get(
            "growth_plan",
            {},
        )
        study_mode = is_study_mode(state)

        first_section = (
            script.sections[
                0
            ].content[
                :420
            ]
            if script.sections
            else ""
        )

        prompt = f"""
Improve ONLY the opening of this YouTube narration.

TOPIC
{state.topic or "unknown"}

CURRENT TITLE
{script.title}

CURRENT HOOK
{script.hook}

CURRENT INTRODUCTION
{script.introduction}

FIRST BODY SECTION PREVIEW
{first_section}

GROWTH TARGETS
core_promise={growth.get("core_promise", "")}
hook_blueprint={growth.get("hook_blueprint", "")}
satisfaction_payoff={growth.get("satisfaction_payoff", "")}

STRICT RULES
1. Return only hook + introduction.
2. Preserve factual meaning and uncertainty. Add NO new fact, quote, date,
   number, person, event, source, genre/category, result or claim.
3. Keep the same narration language.
4. Hook should normally be 10-24 spoken words and directly address the topic.
4a. In Study Mode the hook MUST be informative: state a concrete learner problem and the mechanism/payoff the lesson will explain. Prefer a declarative sentence. Never use a generic rhetorical opener such as "Have you ever wondered", "Did you know", "What if", "Imagine", or "Ever wondered".
5. Introduction should normally be 35-75 spoken words.
6. No greeting, channel intro, "In today's video", "Before we begin", or
   early like/subscribe CTA.
7. Do not repeat the title mechanically.
8. First 30 seconds must immediately deliver useful context and make the next
   section feel worth watching.
9. Do not rewrite or summarize away body content.
10. Return only OpeningRetention JSON.
"""

        optimized = await self._llm.generate_structured(
            prompt,
            OpeningRetention,
            system_prompt=(
                "Improve only the opening for retention. "
                "Do not invent facts and do not rewrite the body."
            ),
        )

        hook = self._clean(
            optimized.hook
        )
        introduction = self._clean(
            optimized.introduction
        )

        candidate_hook_words = self._count(
            hook
        )
        candidate_intro_words = self._count(
            introduction
        )

        hook_ok = (
            5 <= candidate_hook_words <= 35
            and (not study_mode or self._informative_study_hook(hook))
        )
        intro_ok = 20 <= candidate_intro_words <= 110
        opening_ok = hook_ok and intro_ok

        original_opening_words = max(
            1,
            before[
                "hook_words"
            ]
            + before[
                "intro_words"
            ],
        )

        candidate_opening_words = (
            candidate_hook_words
            + candidate_intro_words
        )

        ratio = (
            candidate_opening_words
            / original_opening_words
        )

        size_ok = (
            0.70
            <= ratio
            <= 1.20
        )

        if opening_ok and size_ok:
            # Preserve every non-opening field exactly.
            state.script = YouTubeScript(
                title=script.title,
                hook=hook,
                introduction=introduction,
                sections=script.sections,
                conclusion=script.conclusion,
                call_to_action=script.call_to_action,
                estimated_duration_minutes=(
                    script.estimated_duration_minutes
                ),
            )

            state.metadata[
                "retention_review"
            ] = {
                "applied": True,
                "scope": "opening_only",
                "before": before,
                "after": self._metrics(
                    state.script
                ),
            }

        elif hook_ok:
            # A strong informative hook is more important than accepting an
            # over-expanded introduction. Apply only the hook and keep the
            # already-approved introduction/body byte-for-byte.
            state.script = YouTubeScript(
                title=script.title,
                hook=hook,
                introduction=script.introduction,
                sections=script.sections,
                conclusion=script.conclusion,
                call_to_action=script.call_to_action,
                estimated_duration_minutes=script.estimated_duration_minutes,
            )
            state.metadata["retention_review"] = {
                "applied": True,
                "scope": "hook_only",
                "before": before,
                "after": self._metrics(state.script),
                "reason": "optimized intro rejected; informative hook retained",
            }
            print("[RETENTION] Applied informative hook only; kept approved introduction.")

        else:
            grounded_hook = (
                self._source_grounded_hook(first_section)
                if study_mode and not self._informative_study_hook(script.hook)
                else ""
            )
            if grounded_hook and self._informative_study_hook(grounded_hook):
                state.script = YouTubeScript(
                    title=script.title,
                    hook=grounded_hook,
                    introduction=script.introduction,
                    sections=script.sections,
                    conclusion=script.conclusion,
                    call_to_action=script.call_to_action,
                    estimated_duration_minutes=script.estimated_duration_minutes,
                )
                state.metadata["retention_review"] = {
                    "applied": True,
                    "scope": "source_grounded_hook",
                    "before": before,
                    "after": self._metrics(state.script),
                    "reason": "generic hook replaced with an exact informative sentence from section 1",
                }
                print("[RETENTION] Replaced generic hook with source-grounded informative hook.")
            else:
                reasons = []

                if not opening_ok:
                    reasons.append(
                        "opening word limits failed"
                    )

                if not size_ok:
                    reasons.append(
                        f"opening size ratio={ratio:.2f}"
                    )

                state.metadata[
                    "retention_review"
                ] = {
                    "applied": False,
                    "scope": "opening_only",
                    "before": before,
                    "reason": "; ".join(
                        reasons
                    ),
                }

                print(
                    "[RETENTION] Opening candidate rejected; "
                    + "; ".join(
                        reasons
                    )
                )

        final = self._metrics(
            state.script
        )

        print(
            "[RETENTION] opening-only: "
            f"hook={final['hook_words']} words, "
            f"intro={final['intro_words']} words, "
            f"total={final['total_words']} words"
        )

        state.status = (
            "retention_optimized"
        )

        return state

    @classmethod
    def _metrics(
        cls,
        script: YouTubeScript,
    ) -> dict[str, int | bool]:
        hook_words = cls._count(
            script.hook
        )

        intro_words = cls._count(
            script.introduction
        )

        total = cls._count(
            " ".join(
                [
                    script.hook,
                    script.introduction,
                    *(
                        section.content
                        for section
                        in script.sections
                    ),
                    script.conclusion,
                    script.call_to_action,
                ]
            )
        )

        lower_opening = (
            script.hook
            + " "
            + script.introduction
        ).lower()

        generic_intro = any(
            phrase in lower_opening
            for phrase in (
                "welcome back",
                "welcome to",
                "in today's video",
                "in this video, we're going to",
                "before we begin",
            )
        )

        return {
            "hook_words": hook_words,
            "intro_words": intro_words,
            "total_words": total,
            "generic_intro": generic_intro,
        }

    @staticmethod
    def _informative_study_hook(text: str) -> bool:
        value = re.sub(r"\s+", " ", text).strip().lower()
        if not value:
            return False
        generic_starts = (
            "have you ever wondered", "did you know", "what if", "imagine ",
            "ever wondered", "have you wondered", "do you know",
        )
        if value.startswith(generic_starts):
            return False
        # A hook should communicate an actual relationship/problem, not just
        # announce that a topic exists. Verbs below are intentionally broad so
        # this works for tech, math, science and general study subjects.
        mechanism_terms = (
            "because", "without", "instead", "connect", "turn", "changes",
            "causes", "solves", "lets", "allows", "fails", "works",
            "moves", "converts", "explains", "predicts", "controls",
            "cannot", "can’t", "needs", "requires", "replaces", "bottleneck",
            "lack", "lacks", "problem", "challenge", "prevents", "reduces",
        )
        return any(term in value for term in mechanism_terms) and len(value.split()) >= 8

    @classmethod
    def _source_grounded_hook(cls, first_section: str) -> str:
        """Return an informative sentence already present in approved body text.

        This guarantees a factual fallback without inventing a new claim when an
        LLM returns a generic rhetorical hook or the optimized opening is rejected.
        """
        clean = re.sub(r"\s+", " ", first_section).strip()
        if not clean:
            return ""
        sentences = re.split(r"(?<=[.!?])\s+", clean)
        for sentence in sentences[:4]:
            candidate = sentence.strip()
            words = cls._count(candidate)
            if 8 <= words <= 30 and cls._informative_study_hook(candidate):
                return candidate
        return ""

    @staticmethod
    def _clean(
        text: str,
    ) -> str:
        return re.sub(
            r"\s+",
            " ",
            text,
        ).strip()

    @staticmethod
    def _count(
        text: str,
    ) -> int:
        return len(
            re.findall(
                r"\b[\w@./+-]+\b",
                text,
                flags=re.UNICODE,
            )
        )
