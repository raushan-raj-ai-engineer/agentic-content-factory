from __future__ import annotations

from content_factory.agents.study_animation_director import StudyAnimationDirectorAgent
from content_factory.models.content import ScriptSection, YouTubeScript, VisualScene
from content_factory.utils.study_script_quality import study_script_quality_report
from content_factory.visual.study_storyboard import StudySceneStoryboard, StudyVisualBeat, StudyVisualObject


def _scene(sid: int, title: str, description: str) -> VisualScene:
    return VisualScene(
        id=sid,
        title=title,
        description=description,
        visual_type="technical_diagram",
        voice_segment_id=sid,
        subject=title,
        key_elements=[title],
        composition="teaching",
        style="clean",
        avoid=[],
    )


def _generic(sid: int) -> StudySceneStoryboard:
    return StudySceneStoryboard(
        scene_id=sid,
        purpose="generic",
        layout="left_to_right",
        objects=[
            StudyVisualObject(id="a", kind="node", label="Input", slot="left_mid"),
            StudyVisualObject(id="b", kind="node", label="Process", slot="center"),
            StudyVisualObject(id="c", kind="node", label="Result", slot="right_mid"),
        ],
        beats=[
            StudyVisualBeat(cue="one", action="reveal", target="a"),
            StudyVisualBeat(cue="two", action="reveal", target="b"),
            StudyVisualBeat(cue="three", action="connect", target="b", source="a", destination="b"),
            StudyVisualBeat(cue="four", action="select", target="c"),
        ],
    )


def test_script_quality_blocks_placeholder_and_repeated_boilerplate() -> None:
    repeated = (
        "Testing must verify tool selection logic, argument validity, action ordering, "
        "completion triggers, error handling, permission checks, and safeguards."
    )
    script = YouTubeScript(
        title="AI Agents",
        hook="Agents act through tools.",
        introduction="This lesson explains the loop.",
        sections=[
            ScriptSection(title="Part 3", content=repeated + " First example."),
            ScriptSection(title="Implementation", content=repeated + " Second example."),
            ScriptSection(title="Verification", content=repeated + " Third example."),
        ],
        conclusion="Recap.",
        call_to_action="Practice it.",
        estimated_duration_minutes=8,
    )
    report = study_script_quality_report(script)
    assert report["passed"] is False
    assert report["placeholder_titles"] == ["Part 3"]
    assert report["repeated_sentences"]


def test_agent_tool_selection_uses_request_agent_tool_result_not_safety_gate() -> None:
    scene = _scene(
        6,
        "Tool Selection Logic",
        "The user asks for weather. The agent selects the weather API, calls the tool, observes the returned data, and formats the response.",
    )
    fixed = StudyAnimationDirectorAgent._repair_topic_specific_teaching(
        _generic(6), scene, "AI Agents Explained: How Agentic AI Works"
    )
    kinds = {obj.kind for obj in fixed.objects}
    assert {"search_ui", "agent", "tool", "api", "answer_panel"} <= kinds
    assert fixed.layout == "browser_demo"
    assert "gate" not in kinds


def test_agent_permission_scene_is_the_only_kind_that_needs_boundary() -> None:
    scene = _scene(
        18,
        "Verification and Edge Case Testing of AI Agents",
        "Before the tool runs, validate permission. If the user lacks access to a private file, return access denied and do not execute the tool.",
    )
    fixed = StudyAnimationDirectorAgent._repair_topic_specific_teaching(
        _generic(18), scene, "AI Agents Explained: How Agentic AI Works"
    )
    assert fixed.layout == "boundary"
    assert any(obj.kind == "shield" for obj in fixed.objects)


def test_agent_no_progress_failure_uses_feedback_loop_not_allow_block() -> None:
    scene = _scene(
        19,
        "Verification and Edge Case Testing of AI Agents",
        "A common failure is tool overuse: the agent calls the same tool repeatedly without progress. Completion checks should stop or retry with a clear failure.",
    )
    fixed = StudyAnimationDirectorAgent._repair_topic_specific_teaching(
        _generic(19), scene, "AI Agents Explained: How Agentic AI Works"
    )
    assert fixed.layout == "freeform"
    actions = {beat.action for beat in fixed.beats}
    assert "allow" not in actions
    assert "reject" not in actions
    assert {"send", "return", "compare"} <= actions
