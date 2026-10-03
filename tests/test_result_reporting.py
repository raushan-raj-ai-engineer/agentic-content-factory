from pathlib import Path

from content_factory.models.content import ContentStrategy, ScriptSection, YouTubeScript
from content_factory.orchestration.state import WorkflowState
from content_factory.result_reporting import print_compact_result, write_workflow_result


def test_compact_result_does_not_dump_full_script(capsys, tmp_path: Path) -> None:
    state = WorkflowState(run_id="abc123", topic="RAG")
    state.status = "completed"
    state.strategy_approved = True
    state.script_approved = True
    state.production_approved = True
    state.metadata.update({"llm_provider": "gemini", "llm_model": "flash", "content_mode": "study"})
    state.strategy = ContentStrategy(
        topic="RAG",
        audience="beginners",
        angle="teach",
        hook="hook",
        content_type="Educational Study Video",
        estimated_duration_minutes=12,
    )
    marker = "FULL_SCRIPT_BODY_SHOULD_NOT_BE_PRINTED"
    state.script = YouTubeScript(
        title="RAG Explained",
        hook="hook",
        introduction=marker,
        sections=[ScriptSection(title="Basics", content="Teach the concept clearly.")],
        conclusion="done",
        call_to_action="practice",
        estimated_duration_minutes=7,
    )
    result_path = write_workflow_result(state, root=tmp_path)
    print_compact_result(state, result_path=result_path)
    out = capsys.readouterr().out
    assert "RAG Explained" in out
    assert marker not in out
    assert "Full result JSON:" in out
    assert result_path.is_file()
    assert marker in result_path.read_text(encoding="utf-8")


import pytest


@pytest.mark.asyncio
async def test_study_duration_estimate_is_not_clamped() -> None:
    from content_factory.agents.strategy_grounding import StrategyGroundingAgent

    state = WorkflowState(run_id="duration-run", topic="Deep AI Architecture")
    state.metadata["content_mode"] = "study"
    state.strategy = ContentStrategy(
        topic="Deep AI Architecture",
        audience="beginners",
        angle="Teach architecture from first principles",
        hook="How does it work?",
        content_type="Educational Study Video",
        estimated_duration_minutes=14,
    )

    result = await StrategyGroundingAgent().execute(state)

    assert result.strategy is not None
    assert result.strategy.estimated_duration_minutes == 14
    assert result.metadata["topic_grounding"]["target_duration_minutes"] == 14
