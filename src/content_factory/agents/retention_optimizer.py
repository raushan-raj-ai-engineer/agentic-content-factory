from __future__ import annotations

import json
import re

from pydantic import BaseModel

from content_factory.agents.base import Agent
from content_factory.llm.base import LLMProvider
from content_factory.models.content import YouTubeScript
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
4. Hook should normally be 8-22 spoken words and directly address the topic.
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

        opening_ok = (
            5
            <= candidate_hook_words
            <= 35
            and 20
            <= candidate_intro_words
            <= 110
        )

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
