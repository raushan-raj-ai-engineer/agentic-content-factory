from content_factory.agents.research_planner import ResearchPlannerAgent
from content_factory.research.trend_signals import DiscoverySignal


def signal(topic: str, *headlines: str) -> DiscoverySignal:
    return DiscoverySignal(
        topic=topic,
        raw_topic=topic,
        score=80,
        related_headlines=list(headlines),
    )


def test_technical_category_rejects_sports_weather_and_accepts_tech():
    assert not ResearchPlannerAgent._candidate_matches_category(
        signal("India Vs Panama"), "technical"
    )
    assert not ResearchPlannerAgent._candidate_matches_category(
        signal("Weather Tomorrow"), "technical"
    )
    assert ResearchPlannerAgent._candidate_matches_category(
        signal("RAG with Vector Databases"), "technical"
    )
    assert ResearchPlannerAgent._candidate_matches_category(
        signal("Playwright TypeScript Fixtures"), "technical"
    )
    assert ResearchPlannerAgent._candidate_matches_category(
        signal("ChatGPT"), "technical"
    )


def test_ai_category_is_narrower_than_general_technical():
    assert ResearchPlannerAgent._candidate_matches_category(
        signal("AI Agents with Ollama"), "ai"
    )
    assert not ResearchPlannerAgent._candidate_matches_category(
        signal("PostgreSQL Index Tuning"), "ai"
    )


def test_software_testing_category_requires_quality_testing_signal():
    assert ResearchPlannerAgent._candidate_matches_category(
        signal("Playwright API Testing"), "software_testing"
    )
    assert ResearchPlannerAgent._candidate_matches_category(
        signal("RAG Quality Evaluation", "How teams approach LLM testing"),
        "software_testing",
    )
    assert not ResearchPlannerAgent._candidate_matches_category(
        signal("Cubs Vs Red Sox"), "software_testing"
    )


def test_category_fallbacks_never_include_unrelated_topics():
    items = ResearchPlannerAgent._add_category_fallbacks([], "technical", minimum=7)
    assert len(items) == 7
    assert all(
        ResearchPlannerAgent._candidate_matches_category(item, "technical")
        for item in items
    )


def test_related_headlines_cannot_rescue_off_domain_topic():
    assert not ResearchPlannerAgent._candidate_matches_category(
        signal(
            "Supreme Court",
            "Court discusses a voter database and AI generated evidence",
        ),
        "technical",
    )
    assert not ResearchPlannerAgent._candidate_matches_category(
        signal(
            "Australia Vs",
            "AI predicts the match result using a machine learning model",
        ),
        "technical",
    )


def test_direct_technical_topic_can_pass_even_with_nontech_context():
    assert ResearchPlannerAgent._candidate_matches_category(
        signal("AI election security testing"),
        "technical",
    )
