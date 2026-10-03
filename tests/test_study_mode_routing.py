from __future__ import annotations

from content_factory.agents.fact_checker import FactCheckerAgent
from content_factory.agents.packaging_optimizer import PackagingOptimizerAgent
from content_factory.agents.script_writer_chunked import _build_prompt as chunk_prompt
from content_factory.agents.strategy_grounding import StrategyGroundingAgent
from content_factory.modes import infer_content_mode, is_study_mode
from content_factory.models.content import ContentStrategy, FactCheckResult, YouTubeScript
from content_factory.orchestration.state import WorkflowState


class CapturingLLM:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate_structured(self, prompt, model, **kwargs):
        self.prompts.append(prompt)
        if model is FactCheckResult:
            return FactCheckResult(approved=True, score=95, issues=[])
        raise AssertionError(model)


def script() -> YouTubeScript:
    return YouTubeScript(
        title="Model Context Protocol MCP",
        hook="What problem does MCP solve?",
        introduction="MCP connects AI applications with external capabilities.",
        sections=[{"title": "Mental model", "content": "A host uses clients to communicate with MCP servers."}],
        conclusion="Verify tool permissions and outputs.",
        call_to_action="Build one small MCP example.",
        estimated_duration_minutes=6,
    )


def strategy() -> ContentStrategy:
    return ContentStrategy(
        topic="Model Context Protocol MCP",
        audience="beginner developers",
        angle="Teach MCP architecture, tools, resources, prompts, and testing with a simple example",
        hook="What problem does MCP solve, and how does it work?",
        content_type="educational video",
        estimated_duration_minutes=8,
    )


def test_content_mode_inference_for_technical_topics():
    assert infer_content_mode(category="technical") == "study"
    assert infer_content_mode(category="ai") == "study"
    assert infer_content_mode(topic="RAG with Python for beginners") == "study"
    assert infer_content_mode(topic="Model Context Protocol MCP") == "study"
    assert infer_content_mode(topic="football highlights") == "current"


async def test_strategy_grounding_does_not_turn_study_video_into_news():
    state = WorkflowState(run_id="study", topic="Model Context Protocol MCP")
    state.metadata["content_mode"] = "study"
    state.strategy = strategy()
    result = await StrategyGroundingAgent().execute(state)
    assert is_study_mode(result)
    assert "current public reports" not in result.strategy.angle.lower()
    assert "trending" not in result.strategy.hook.lower()
    assert result.metadata["topic_grounding"]["content_mode"] == "study"
    assert result.metadata["topic_grounding"]["target_duration_minutes"] == 8


async def test_fact_checker_uses_study_policy_for_evergreen_tech():
    state = WorkflowState(run_id="study", topic="Model Context Protocol MCP")
    state.metadata["content_mode"] = "study"
    state.script = script()
    llm = CapturingLLM()
    result = await FactCheckerAgent(llm)._check(state)
    assert result.approved
    prompt = llm.prompts[-1]
    assert "STUDY-MODE FACT-CHECK POLICY" in prompt
    assert "Do NOT reject a correct stable technical concept" in prompt


def test_chunk_prompt_is_curriculum_first_in_study_mode():
    state = WorkflowState(run_id="study", topic="Model Context Protocol MCP")
    state.metadata["content_mode"] = "study"
    state.metadata["topic_grounding"] = {"target_duration_minutes": 8}
    state.strategy = strategy()
    class Agent:
        def _target_language_name(self, state): return "English"
    text = chunk_prompt(Agent(), state, index=2, target_words=250, context="context", chunks=[], rescue=False)
    assert "STUDY MODE POLICY" in text
    assert "simple analogy/mental model" in text
    assert "Trend/news material is optional discovery context only" in text


def test_study_packaging_fallbacks_are_tutorial_titles():
    state = WorkflowState(run_id="study", topic="Model Context Protocol MCP")
    state.metadata["content_mode"] = "study"
    state.script = script()
    titles = PackagingOptimizerAgent._safe_titles(state)
    assert titles[0].endswith("Beginner Guide")
    assert titles[1].startswith("How ")
    assert all("Current Reports" not in value for value in titles)

async def test_study_mode_skips_news_enrichment_without_network():
    from content_factory.agents.evidence_enricher import EvidenceEnrichmentAgent
    state = WorkflowState(run_id="study", topic="Model Context Protocol MCP")
    state.metadata["content_mode"] = "study"
    result = await EvidenceEnrichmentAgent().execute(state)
    assert result.metadata["enriched_evidence"] == []
    assert result.metadata["evidence_summary"]["mode"] == "study"

class ContradictoryPassLLM:
    async def generate_structured(self, prompt, model, **kwargs):
        if model is FactCheckResult:
            return FactCheckResult(
                approved=False,
                score=70,
                issues=["No material false or unsupported current claims remain."],
            )
        raise AssertionError(model)


async def test_fact_checker_normalizes_no_issue_status_sentence_to_pass():
    state = WorkflowState(run_id="study-fact-normalize", topic="RAG with Python for beginners")
    state.metadata["content_mode"] = "study"
    state.script = script()
    result = await FactCheckerAgent(ContradictoryPassLLM())._check(state)
    assert result.approved is True
    assert result.issues == []
    assert result.score == 70

class ActionableIssueLLM:
    async def generate_structured(self, prompt, model, **kwargs):
        if model is FactCheckResult:
            return FactCheckResult(
                approved=False,
                score=60,
                issues=["No supplied evidence supports the claimed 95% retrieval accuracy."],
            )
        raise AssertionError(model)


async def test_fact_checker_does_not_filter_actionable_no_evidence_issue():
    state = WorkflowState(run_id="study-fact-actionable", topic="RAG with Python for beginners")
    state.metadata["content_mode"] = "study"
    state.script = script()
    result = await FactCheckerAgent(ActionableIssueLLM())._check(state)
    assert result.approved is False
    assert result.issues == ["No supplied evidence supports the claimed 95% retrieval accuracy."]
    assert result.score == 60
