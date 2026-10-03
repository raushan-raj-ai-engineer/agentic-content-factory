from __future__ import annotations

import pytest

from content_factory.agents.content_producer import ContentProductionAgent
from content_factory.agents.study_animation_director import StudyAnimationDirectorAgent
from content_factory.models.content import VisualScene, YouTubeScript
from content_factory.orchestration.state import WorkflowState
from content_factory.visual.study_storyboard import StudySceneStoryboard, StudyVisualBeat, StudyVisualObject


def _scene(phase: str) -> VisualScene:
    return VisualScene(
        id=2,
        title="Tool Selection Logic — 2",
        description=(
            "The agent reads the request, compares available tools, selects the matching tool, "
            "executes it, and observes the result before deciding whether the task is complete."
        ),
        visual_type="technical_workflow",
        voice_segment_id=2,
        subject="AI agent tool selection",
        key_elements=["agent", "request", "available tools", "result"],
        composition="flow",
        style="study",
        learning_phase=phase,
        chapter_title="Tool Selection Logic",
        chapter_scene_index=2,
        chapter_scene_count=4,
    )


def _storyboard() -> StudySceneStoryboard:
    objects = [
        StudyVisualObject(id="request", kind="search_ui", label="Request", slot="left_mid"),
        StudyVisualObject(id="agent", kind="agent", label="AI Agent", slot="center"),
        StudyVisualObject(id="tool", kind="tool", label="Available Tools", slot="right_top"),
        StudyVisualObject(id="result", kind="answer_panel", label="Result", slot="right_bottom"),
    ]
    beats = [
        StudyVisualBeat(cue="agent reads the request", action="reveal", target="request"),
        StudyVisualBeat(cue="compares available tools", action="reveal", target="tool"),
        StudyVisualBeat(cue="selects the matching tool", action="select", target="tool"),
        StudyVisualBeat(cue="observes the result", action="stream", target="result", source="tool"),
    ]
    return StudySceneStoryboard(
        scene_id=2,
        purpose="Teach tool selection",
        layout="radial",
        objects=objects,
        beats=beats,
    )


def test_phase_contract_explain_then_flow():
    assert ContentProductionAgent._study_learning_phase(
        block_kind="section", chunk_index=1, chunk_count=4, text="A tool is an external capability."
    ) == "explain"
    assert ContentProductionAgent._study_learning_phase(
        block_kind="section", chunk_index=2, chunk_count=4, text="First the agent reads the request, then it selects a tool."
    ) == "flow"


def test_long_single_study_section_is_split_for_explain_then_flow():
    text = (
        "An AI agent is a system that chooses actions to achieve a goal. "
        "The important idea is that it can use tools instead of only returning text. "
        "The agent reads the current request and available context. "
        "It then selects a tool, executes it, observes the result, and decides what to do next."
    )
    chunks = ContentProductionAgent._ensure_study_pedagogy_chunks(
        [text], original_text=text, block_kind="section", target_words=48
    )
    assert len(chunks) == 2
    assert "system that chooses actions" in chunks[0]
    assert "selects a tool" in chunks[1]


def test_explain_phase_is_not_rendered_as_full_process_flow():
    fixed = StudyAnimationDirectorAgent._repair_beginner_pedagogy(
        _storyboard(), _scene("explain"), "AI Agents Explained"
    )
    assert fixed.learning_phase == "explain"
    assert fixed.teaching_pattern == "concept_explain"
    assert fixed.layout == "stack"
    assert fixed.layout != "left_to_right"


def test_flow_phase_is_explicit_left_to_right_mechanism():
    fixed = StudyAnimationDirectorAgent._repair_beginner_pedagogy(
        _storyboard(), _scene("flow"), "AI Agents Explained"
    )
    assert fixed.learning_phase == "flow"
    assert fixed.teaching_pattern == "mechanism_flow"
    assert fixed.layout == "left_to_right"
    assert any(beat.action == "send" for beat in fixed.beats)
    assert fixed.camera_style == "follow"


@pytest.mark.asyncio
async def test_content_producer_emits_beginner_phase_metadata():
    state = WorkflowState(run_id="v110", topic="AI Agents for Beginners", script_approved=True)
    state.metadata["content_mode"] = "study"
    state.script = YouTubeScript(
        title="AI Agents for Beginners",
        hook="An agent can act through tools to complete a goal.",
        introduction=(
            "An AI agent is a system that chooses actions toward a goal. "
            "It differs from a chatbot because it can use external tools. "
            "The simplest mental model is goal, decision, action, and observation."
        ),
        sections=[{
            "title": "Tool Selection",
            "content": (
                "Tool selection means choosing the capability that matches the current need. "
                "The agent should understand the request before choosing anything. "
                "First it reads the request and available tool descriptions. "
                "Next it compares those capabilities, selects one tool, executes it, and observes the returned result. "
                "For example, a weather request should route to a weather tool rather than a calculator. "
                "The result should then be checked before the agent decides whether the task is finished."
            ),
        }],
        conclusion="A useful agent separates understanding, action, observation, and verification.",
        call_to_action="Build one small two-tool example and inspect each step.",
        estimated_duration_minutes=2,
    )
    result = await ContentProductionAgent().execute(state)
    section_scenes = [
        scene for scene in result.production_plan.visual_scenes
        if scene.chapter_title == "Tool Selection"
    ]
    assert len(section_scenes) >= 2
    assert section_scenes[0].learning_phase == "explain"
    assert section_scenes[1].learning_phase == "flow"
    assert all(scene.chapter_scene_count == len(section_scenes) for scene in section_scenes)

@pytest.mark.asyncio
async def test_study_mode_preserves_nontechnical_subject_domain():
    state = WorkflowState(run_id="science-study", topic="Photosynthesis for Beginners", script_approved=True)
    state.metadata["content_mode"] = "study"
    state.script = YouTubeScript(
        title="Photosynthesis for Beginners",
        hook="Plants convert light energy into stored chemical energy.",
        introduction="Photosynthesis is how plants use light, water, and carbon dioxide to make sugars.",
        sections=[{
            "title": "The Basic Process",
            "content": (
                "Chlorophyll absorbs light energy in the leaf. Water and carbon dioxide provide the raw materials. "
                "The reactions use that energy to form sugars and release oxygen. "
                "First light is captured, then the chemical reactions transfer energy, and finally sugar is produced."
            ),
        }],
        conclusion="The process connects light capture to chemical energy storage.",
        call_to_action="Trace the inputs and outputs once more.",
        estimated_duration_minutes=2,
    )
    result = await ContentProductionAgent().execute(state)
    assert result.metadata["domain_classification"]["domain"] == "science"
