from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from content_factory.agents.base import Agent
from content_factory.llm.base import LLMProvider
from content_factory.orchestration.state import WorkflowState
from content_factory.modes import is_study_mode


class GrowthPlan(BaseModel):
    audience_entry_point: str
    core_promise: str
    why_now: str
    hook_blueprint: str
    satisfaction_payoff: str
    open_loops: list[str] = Field(default_factory=list)
    pattern_interrupt_interval_seconds: int = 35
    comment_question: str
    next_video_bridge: str
    short_clip_angles: list[str] = Field(default_factory=list)


class GrowthStrategyAgent(Agent):
    """
    Build an Appeal / Engagement / Satisfaction plan from the selected topic.

    No "viral guarantee" is produced. The goal is to improve the things
    creators can actually control: packaging, hook, pacing, payoff and viewer
    satisfaction.
    """

    def __init__(
        self,
        llm: LLMProvider,
    ) -> None:
        self._llm = llm

    @property
    def name(self) -> str:
        return "Growth Strategy Agent"

    async def execute(
        self,
        state: WorkflowState,
    ) -> WorkflowState:
        if state.strategy is None:
            raise ValueError(
                "Content strategy is required before growth planning."
            )

        evidence = self._evidence_summary(state)
        study_mode = is_study_mode(state)
        relevance_rule = (
            "For study mode, why_now should explain the practical learning/career value of the concept; do not force a trending-news reason."
            if study_mode
            else "why_now must be grounded in the topic being currently relevant; do not invent a date/event."
        )

        prompt = f"""
Create a viewer-growth plan for this YouTube video.

TOPIC
{state.topic or state.strategy.topic}

AUDIENCE
{state.strategy.audience}

ANGLE
{state.strategy.angle}

HOOK IDEA
{state.strategy.hook}

CURRENT TREND / YOUTUBE EVIDENCE
{evidence}

GOAL
Improve:
- APPEAL: make the concept easy to understand and worth clicking
- ENGAGEMENT: make the first seconds and middle of the video hold attention
- SATISFACTION: deliver the promised value clearly without filler/clickbait

RULES
1. Do not invent facts.
2. The core promise must be fully deliverable by the final script.
3. {relevance_rule}
4. Hook blueprint should reach the viewer's reason for clicking immediately.
5. Avoid channel greetings, logo intros, "welcome back", and long setup.
6. Suggest 1-3 open loops only; too many feels manipulative.
7. Pattern-interrupt interval should be 20-45 seconds, but visual changes must
   still match narration.
8. Comment question must invite a genuine opinion, not engagement bait.
9. next_video_bridge should naturally lead to a related future video.
10. short_clip_angles should be 2-3 standalone moments that could later become
    Shorts, without changing facts.
11. Return only GrowthPlan JSON.
"""

        plan = await self._llm.generate_structured(
            prompt,
            GrowthPlan,
            system_prompt=(
                "You are a YouTube growth strategist focused on audience value, "
                "retention and accurate packaging. Never promise virality."
            ),
        )

        plan.pattern_interrupt_interval_seconds = max(
            20,
            min(
                45,
                plan.pattern_interrupt_interval_seconds,
            ),
        )
        plan.open_loops = plan.open_loops[:3]
        plan.short_clip_angles = plan.short_clip_angles[:3]

        state.metadata["growth_plan"] = plan.model_dump()
        state.status = "growth_planned"

        print(
            "[GROWTH] Plan ready: "
            f"pattern_interrupt≈{plan.pattern_interrupt_interval_seconds}s, "
            f"open_loops={len(plan.open_loops)}, "
            f"short_angles={len(plan.short_clip_angles)}"
        )

        return state

    @staticmethod
    def _evidence_summary(
        state: WorkflowState,
    ) -> str:
        if state.research is None:
            return "No external trend evidence attached."

        evidence = state.research.top_candidate.evidence[:8]

        if not evidence:
            return "No fresh YouTube evidence attached."

        return "\n".join(
            (
                f"- {item.title} | "
                f"views={item.view_count} | "
                f"published={item.published_at or 'unknown'}"
            )
            for item in evidence
        )
