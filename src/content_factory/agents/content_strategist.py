from content_factory.agents.base import Agent
from content_factory.llm.base import LLMProvider
from content_factory.models.content import ContentStrategy
from content_factory.modes import is_study_mode
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
        study_mode = is_study_mode(state)
        study_rules = ""
        if study_mode:
            study_rules = """
STUDY-VIDEO STRATEGY REQUIREMENTS
- Treat this as a beginner-friendly educational video taught by a subject-matter expert.
- The learning arc should be: learner problem → plain-language theory → simple analogy or mental model → step-by-step mechanism/flow → practical example or code → verification → concrete edge cases/limitations → practice takeaway.
- Do not make the angle primarily news commentary just because the topic was discovered from current trends. Current evidence may motivate the topic, but the video must teach the underlying concept.
- Define important technical terms before relying on them.
- Prefer one clear concept per section over dense jargon.
- Estimate duration from the depth actually needed to teach the topic well. Do not force a standard video length.
- The hook must be informative, not a generic rhetorical question. State a concrete learner problem and the mechanism/payoff the lesson will reveal. Avoid openings such as "Have you ever wondered", "Did you know", "What if", or "Imagine" unless the sentence itself contains a concrete factual mechanism.
"""

        localization = str(
            state.metadata.get("localization_style")
            or state.metadata.get("target_language_name")
            or ""
        ).strip()
        locale_rule = ""
        if localization:
            locale_rule = (
                f"\nLOCALIZATION: Write for {localization}. "
                "Use natural vocabulary, examples, and phrasing for that audience. "
                "Do not force location-specific references when they do not help the lesson.\n"
            )

        requested_scope = str(state.metadata.get("requested_topic") or top_candidate.topic).strip()
        prompt = f"""
Create a YouTube content strategy for this topic:

Topic: {top_candidate.topic}
User-requested scope: {requested_scope}
Trend score: {top_candidate.trend_score}
Audience fit: {top_candidate.audience_fit}
Competition: {top_candidate.competition}
Opportunity score: {top_candidate.opportunity_score}
{study_rules}
{locale_rule}
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
6. estimated_duration_minutes must be an integer derived from topic complexity and audience needs. In Study Mode it is the approved teaching-depth target that downstream script generation should follow within a narrow tolerance unless the user explicitly overrides it.
7. If User-requested scope contains explicit facets after a colon, em dash, comma list, or phrase such as "including", DO NOT silently drop them. The display topic may be concise, but the angle must preserve those requested teaching facets so downstream script generation covers them.
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
