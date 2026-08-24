from content_factory.agents.base import Agent
from content_factory.llm.base import LLMProvider
from content_factory.models.content import ContentStrategy
from content_factory.orchestration.state import WorkflowState


class ContentStrategistAgent(Agent):
    """Create content strategy using an LLM."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    @property
    def name(self) -> str:
        return "Content Strategist Agent"

    async def execute(self, state: WorkflowState) -> WorkflowState:
        """Generate and validate a content strategy."""
        if state.research is None:
            raise ValueError("Research data is required.")

        top_candidate = state.research.top_candidate

        prompt = f"""
Create a YouTube content strategy for this topic:

Topic: {top_candidate.topic}
Trend score: {top_candidate.trend_score}
Audience fit: {top_candidate.audience_fit}
Competition: {top_candidate.competition}
Opportunity score: {top_candidate.opportunity_score}

Return EXACTLY one JSON object.

The JSON object MUST contain exactly these fields:

{{
  "topic": "string",
  "audience": "string",
  "angle": "string",
  "hook": "string",
  "content_type": "string",
  "estimated_duration_minutes": 8
}}

Rules:
1. Do not create a "strategy" array.
2. Do not create nested objects.
3. Do not include markdown.
4. Do not include explanations.
5. Do not include fields other than the six required fields.
6. estimated_duration_minutes must be an integer.
"""

        strategy = await self._llm.generate_structured(
            prompt,
            ContentStrategy,
            system_prompt=(
                "You are a precise JSON API. "
                "Return exactly one JSON object matching "
                "the requested schema."
            ),
        )

        state.strategy = strategy
        state.topic = strategy.topic
        state.status = "strategy_created"

        return state
