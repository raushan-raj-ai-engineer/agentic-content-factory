from __future__ import annotations

import json
from pathlib import Path

import pytest

from content_factory.agents.study_animation_director import StudyAnimationDirectorAgent
from content_factory.models.content import ContentProductionPlan, VisualScene, VoiceSegment
from content_factory.orchestration.state import WorkflowState
from content_factory.visual.study_storyboard import (
    StudySceneStoryboard,
    StudyStoryboardBatch,
    StudyVisualBeat,
    StudyVisualObject,
    clean_storyboard,
    diversity_report,
)


class FakeStoryboardLLM:
    provider_name = "fake"
    model_name = "fake-model"

    def __init__(self):
        self.calls = []

    async def generate_structured(self, prompt, response_model, **kwargs):
        self.calls.append(kwargs)
        assert response_model is StudyStoryboardBatch
        data = json.loads(prompt.split("SCENES:\n", 1)[1].split("\n\nNON-NEGOTIABLE", 1)[0])
        scenes = []
        for item in data:
            sid = item["scene_id"]
            narration = item["narration"].lower()
            if "code" in narration or "implement" in narration:
                objects = [
                    StudyVisualObject(id="code", kind="code", label="Agent loop", slot="wide_mid", detail=["while task:", "tool = choose_tool()", "result = tool()", "verify(result)"]),
                    StudyVisualObject(id="state", kind="badge", label="Current state", slot="right_bottom"),
                    StudyVisualObject(id="out", kind="terminal", label="Verified result", slot="left_bottom"),
                ]
                beats = [
                    StudyVisualBeat(cue="show code", action="type_code", target="code"),
                    StudyVisualBeat(cue="step 1", action="step_code", target="code", weight=2),
                    StudyVisualBeat(cue="step 2", action="step_code", target="code", weight=2),
                    StudyVisualBeat(cue="state", action="reveal", target="state"),
                    StudyVisualBeat(cue="output", action="reveal", target="out"),
                ]
                layout = "code_plus_state"
            else:
                objects = [
                    StudyVisualObject(id="host", kind="client", label="Host", slot="left_mid"),
                    StudyVisualObject(id="server", kind="server", label="MCP Server", slot="center"),
                    StudyVisualObject(id="tool", kind="tool", label="File Tool", slot="right_mid"),
                    StudyVisualObject(id="packet", kind="packet", label="JSON-RPC", slot="center_bottom"),
                ]
                beats = [
                    StudyVisualBeat(cue="host", action="reveal", target="host"),
                    StudyVisualBeat(cue="server", action="reveal", target="server"),
                    StudyVisualBeat(cue="connect", action="connect", target="server", source="host", destination="server"),
                    StudyVisualBeat(cue="tool", action="reveal", target="tool"),
                    StudyVisualBeat(cue="request", action="send", target="packet", source="host", destination="server", weight=2),
                    StudyVisualBeat(cue="tool call", action="send", target="packet", source="server", destination="tool", weight=2),
                ]
                layout = "left_to_right"
            scenes.append(
                StudySceneStoryboard(
                    scene_id=sid,
                    purpose=f"Teach scene {sid}",
                    layout=layout,
                    objects=objects,
                    beats=beats,
                    reference_keywords=["MCP", "JSON-RPC"],
                )
            )
        return StudyStoryboardBatch(scenes=scenes)


def _scene(sid: int, title: str, description: str) -> VisualScene:
    return VisualScene(
        id=sid,
        title=title,
        description=description,
        visual_type="technical_diagram",
        voice_segment_id=sid,
        subject=title,
        key_elements=["bad generic fragment"],
        composition="teaching",
        style="clean",
        avoid=[],
    )


@pytest.mark.asyncio
async def test_animation_director_writes_narration_driven_storyboards(tmp_path: Path):
    scenes = [
        _scene(1, "Architecture", "The host sends a JSON-RPC request to an MCP server and tool."),
        _scene(2, "Implementation", "Implement the agent loop in code and verify the result."),
    ]
    state = WorkflowState(run_id="run", topic="Model Context Protocol MCP")
    state.metadata["content_mode"] = "study"
    state.production_plan = ContentProductionPlan(
        title="MCP",
        voice_segments=[
            VoiceSegment(id=1, text="a", estimated_duration_seconds=10),
            VoiceSegment(id=2, text="b", estimated_duration_seconds=10),
        ],
        visual_scenes=scenes,
        thumbnail_prompt="thumb",
        youtube_description="desc",
        youtube_tags=["mcp"],
    )
    llm = FakeStoryboardLLM()
    result = await StudyAnimationDirectorAgent(llm, output_root=str(tmp_path)).execute(state)
    assert llm.calls and llm.calls[0]["prefer_native"] is False
    path = Path(result.metadata["study_storyboard_file"])
    assert path.is_file()
    payload = json.loads(path.read_text())
    assert len(payload["scenes"]) == 2
    assert payload["scenes"][0]["objects"][0]["label"] == "Host"
    assert payload["scenes"][1]["layout"] == "code_plus_state"
    assert payload["scenes"][1]["objects"][0]["kind"] == "code"


def test_clean_storyboard_removes_ppt_fragment_labels_and_duplicate_slots():
    sb = StudySceneStoryboard(
        scene_id=1,
        purpose="Explain MCP",
        layout="freeform",
        objects=[
            StudyVisualObject(id="a", kind="node", label="Context", slot="center"),
            StudyVisualObject(id="b", kind="client", label="Host", slot="center"),
            StudyVisualObject(id="c", kind="server", label="MCP Server", slot="center"),
        ],
        beats=[
            StudyVisualBeat(cue="a", action="reveal", target="a"),
            StudyVisualBeat(cue="b", action="reveal", target="b"),
            StudyVisualBeat(cue="c", action="reveal", target="c"),
            StudyVisualBeat(cue="connect", action="connect", target="c", source="b", destination="c"),
        ],
    )
    clean = clean_storyboard(sb, title="Context", topic="Model Context Protocol MCP")
    labels = [o.label for o in clean.objects]
    assert "Context" not in labels
    assert "Host" in labels and "MCP Server" in labels
    slots = [o.slot for o in clean.objects]
    assert len(slots) == len(set(slots))


def test_diversity_report_detects_exact_template_repetition():
    def storyboard(scene_id: int, layout: str) -> StudySceneStoryboard:
        return StudySceneStoryboard(
            scene_id=scene_id,
            purpose="demo",
            layout=layout,
            objects=[
                StudyVisualObject(id="a", kind="client", label="A", slot="left_mid"),
                StudyVisualObject(id="b", kind="server", label="B", slot="center"),
                StudyVisualObject(id="c", kind="packet", label="C", slot="right_mid"),
            ],
            beats=[
                StudyVisualBeat(cue="1", action="reveal", target="a"),
                StudyVisualBeat(cue="2", action="reveal", target="b"),
                StudyVisualBeat(cue="3", action="connect", target="b", source="a", destination="b"),
                StudyVisualBeat(cue="4", action="send", target="c", source="a", destination="b"),
            ],
        )
    report = diversity_report([storyboard(1, "left_to_right"), storyboard(2, "left_to_right")])
    assert report["max_adjacent_repeat"] == 2
    assert report["unique_ratio"] == 0.5


def test_v4_storyboard_motion_sidecar_is_accepted_by_assembler(tmp_path: Path):
    from PIL import Image
    from content_factory.agents.visual_generator import VisualGenerationAgent
    from content_factory.video.local import LocalVideoAssembler

    image = tmp_path / "scene_1.png"
    Image.new("RGB", (1920, 1080), (8, 17, 31)).save(image)
    manifest = image.with_suffix(".png.storyboard.json")
    storyboard = StudySceneStoryboard(
        scene_id=1,
        purpose="Explain request travel",
        layout="left_to_right",
        objects=[
            StudyVisualObject(id="client", kind="client", label="Host", slot="left_mid"),
            StudyVisualObject(id="server", kind="server", label="MCP Server", slot="center"),
            StudyVisualObject(id="packet", kind="packet", label="JSON-RPC", slot="right_mid"),
        ],
        beats=[
            StudyVisualBeat(cue="client", action="reveal", target="client"),
            StudyVisualBeat(cue="server", action="reveal", target="server"),
            StudyVisualBeat(cue="connect", action="connect", target="server", source="client", destination="server"),
            StudyVisualBeat(cue="send", action="send", target="packet", source="client", destination="server"),
        ],
    )
    manifest.write_text(json.dumps(storyboard.model_dump()), encoding="utf-8")
    VisualGenerationAgent._write_study_motion_policy(
        output_path=image,
        visual_type="technical_diagram",
        study_manifest=manifest,
        mode="study_storyboard_manim",
        policy="study-animation-v4-storyboard",
    )
    assert LocalVideoAssembler._motion_mode(str(image)) == "study_storyboard_manim"
    loaded = LocalVideoAssembler._study_semantic_manifest(str(image))
    assert loaded is not None
    assert loaded[1]["layout"] == "left_to_right"


def test_storyboard_cues_are_repaired_to_verbatim_narration():
    narration = "The customer gives an order to the waiter. The waiter carries it to the kitchen and returns the result."
    sb = StudySceneStoryboard(
        scene_id=1,
        purpose="Map restaurant analogy to MCP",
        layout="analogy_map",
        objects=[
            StudyVisualObject(id="customer", kind="person", label="Customer", slot="left_top"),
            StudyVisualObject(id="kitchen", kind="place", label="Kitchen", slot="left_bottom"),
            StudyVisualObject(id="host", kind="host", label="Host", slot="right_top"),
            StudyVisualObject(id="server", kind="server", label="MCP Server", slot="right_bottom"),
        ],
        beats=[
            StudyVisualBeat(cue="show analogy", action="reveal", target="customer"),
            StudyVisualBeat(cue="map host", action="transform", target="host", source="customer"),
            StudyVisualBeat(cue="map server", action="transform", target="server", source="kitchen"),
            StudyVisualBeat(cue="finish", action="highlight", target="server"),
        ],
    )
    repaired = StudyAnimationDirectorAgent._repair_cues(sb, narration)
    normalized = " ".join(narration.lower().split())
    assert all(" ".join(beat.cue.lower().split()) in normalized for beat in repaired.beats)


def test_storyboard_semantic_quality_rewards_real_analogy_transform():
    from content_factory.visual.study_storyboard import storyboard_quality_report

    sb = StudySceneStoryboard(
        scene_id=1,
        purpose="Map kitchen analogy to MCP",
        layout="analogy_map",
        objects=[
            StudyVisualObject(id="customer", kind="person", label="Customer", slot="left_top"),
            StudyVisualObject(id="kitchen", kind="place", label="Kitchen", slot="left_bottom"),
            StudyVisualObject(id="host", kind="host", label="Host", slot="right_top"),
            StudyVisualObject(id="server", kind="server", label="MCP Server", slot="right_bottom"),
        ],
        beats=[
            StudyVisualBeat(cue="customer", action="reveal", target="customer"),
            StudyVisualBeat(cue="kitchen", action="reveal", target="kitchen"),
            StudyVisualBeat(cue="host", action="transform", target="host", source="customer"),
            StudyVisualBeat(cue="server", action="transform", target="server", source="kitchen"),
        ],
    )
    report = storyboard_quality_report([sb])
    assert report["score"] >= 90
    assert report["specialized_scene_pass_ratio"] == 1.0


def test_restaurant_analogy_is_repaired_into_real_world_to_mcp_mapping():
    sb = StudySceneStoryboard(
        scene_id=5,
        purpose="Explain restaurant analogy",
        layout="analogy_map",
        objects=[
            StudyVisualObject(id="a", kind="node", label="Customer", slot="left_top"),
            StudyVisualObject(id="b", kind="client", label="Client", slot="center"),
            StudyVisualObject(id="c", kind="server", label="Server", slot="right_mid"),
        ],
        beats=[
            StudyVisualBeat(cue="customer", action="reveal", target="a"),
            StudyVisualBeat(cue="client", action="reveal", target="b"),
            StudyVisualBeat(cue="server", action="connect", target="c", source="b", destination="c"),
            StudyVisualBeat(cue="done", action="highlight", target="c"),
        ],
    )
    narration = (
        "Imagine a busy restaurant kitchen. The customer gives the waiter an order, "
        "and the waiter carries it to the kitchen pantry. The host uses an MCP client "
        "to communicate with the MCP server through a standard protocol."
    )
    repaired = StudyAnimationDirectorAgent._repair_semantic_requirements(sb, narration, "MCP")
    assert [o.kind for o in repaired.objects] == [
        "person", "person", "place", "host", "client", "server"
    ]
    assert sum(beat.action == "transform" for beat in repaired.beats) == 3


def test_v5_cue_storyboard_motion_sidecar_is_accepted(tmp_path: Path):
    from PIL import Image
    from content_factory.agents.visual_generator import VisualGenerationAgent
    from content_factory.video.local import LocalVideoAssembler

    image = tmp_path / "scene_1.png"
    Image.new("RGB", (1920, 1080), (8, 17, 31)).save(image)
    manifest = image.with_suffix(".png.storyboard.json")
    storyboard = StudySceneStoryboard(
        scene_id=1,
        purpose="Explain request travel",
        layout="left_to_right",
        objects=[
            StudyVisualObject(id="client", kind="client", label="Host", slot="left_mid"),
            StudyVisualObject(id="server", kind="server", label="MCP Server", slot="center"),
            StudyVisualObject(id="packet", kind="packet", label="JSON-RPC", slot="right_mid"),
        ],
        beats=[
            StudyVisualBeat(cue="client sends", action="reveal", target="client"),
            StudyVisualBeat(cue="server receives", action="reveal", target="server"),
            StudyVisualBeat(cue="request travels", action="connect", target="server", source="client", destination="server"),
            StudyVisualBeat(cue="returns data", action="send", target="packet", source="client", destination="server"),
        ],
    )
    manifest.write_text(json.dumps(storyboard.model_dump()), encoding="utf-8")
    VisualGenerationAgent._write_study_motion_policy(
        output_path=image,
        visual_type="technical_diagram",
        study_manifest=manifest,
        mode="study_storyboard_manim",
        policy="study-animation-v5-cue-storyboard",
    )
    loaded = LocalVideoAssembler._study_semantic_manifest(str(image))
    assert loaded is not None
    assert loaded[1]["layout"] == "left_to_right"


def test_boundary_scene_auto_repair_adds_allow_and_reject():
    sb = StudySceneStoryboard(
        scene_id=4,
        purpose="Validate agent input",
        layout="boundary",
        objects=[
            StudyVisualObject(id="req", kind="packet", label="Tool request", slot="left_mid"),
            StudyVisualObject(id="srv", kind="server", label="Tool server", slot="center"),
            StudyVisualObject(id="out", kind="resource", label="Result", slot="right_mid"),
        ],
        beats=[
            StudyVisualBeat(cue="request", action="reveal", target="req"),
            StudyVisualBeat(cue="server", action="reveal", target="srv"),
            StudyVisualBeat(cue="connect", action="connect", target="srv", source="req", destination="srv"),
            StudyVisualBeat(cue="result", action="highlight", target="out"),
        ],
    )
    narration = (
        "Validate every tool input before execution. Reject unauthorized requests and "
        "allow only actions that satisfy the permission boundary."
    )
    fixed = StudyAnimationDirectorAgent._repair_semantic_requirements(sb, narration, "AI Agents")
    assert fixed.layout == "boundary"
    assert {o.kind for o in fixed.objects} & {"gate", "shield", "lock"}
    assert {b.action for b in fixed.beats} >= {"allow", "reject"}


def test_protocol_scene_auto_repair_adds_state_movement():
    sb = StudySceneStoryboard(
        scene_id=20,
        purpose="Show tool response travel",
        layout="left_to_right",
        objects=[
            StudyVisualObject(id="agent", kind="agent", label="Agent", slot="left_mid"),
            StudyVisualObject(id="packet", kind="packet", label="Tool call", slot="center"),
            StudyVisualObject(id="tool", kind="tool", label="Weather API", slot="right_mid"),
        ],
        beats=[
            StudyVisualBeat(cue="agent", action="reveal", target="agent"),
            StudyVisualBeat(cue="tool", action="reveal", target="tool"),
            StudyVisualBeat(cue="connect", action="connect", target="tool", source="agent", destination="tool"),
            StudyVisualBeat(cue="packet", action="highlight", target="packet"),
        ],
    )
    narration = "The agent sends a tool call to the weather API and receives the observation."
    fixed = StudyAnimationDirectorAgent._repair_semantic_requirements(sb, narration, "AI Agents")
    assert {b.action for b in fixed.beats} & {"send", "return", "move"}


def test_quality_auto_repair_recovers_specialized_scene_failures():
    scenes = [
        _scene(4, "Security", "Reject unauthorized tool requests and allow valid requests through the permission boundary."),
        _scene(20, "Tool Flow", "The agent sends a tool call to the API and receives an observation."),
    ]
    broken = [
        StudySceneStoryboard(
            scene_id=4,
            purpose="boundary",
            layout="boundary",
            objects=[
                StudyVisualObject(id="a", kind="packet", label="Request", slot="left_mid"),
                StudyVisualObject(id="b", kind="server", label="Server", slot="center"),
                StudyVisualObject(id="c", kind="resource", label="Result", slot="right_mid"),
            ],
            beats=[
                StudyVisualBeat(cue="1", action="reveal", target="a"),
                StudyVisualBeat(cue="2", action="reveal", target="b"),
                StudyVisualBeat(cue="3", action="connect", target="b", source="a", destination="b"),
                StudyVisualBeat(cue="4", action="highlight", target="c"),
            ],
        ),
        StudySceneStoryboard(
            scene_id=20,
            purpose="flow",
            layout="left_to_right",
            objects=[
                StudyVisualObject(id="a", kind="agent", label="Agent", slot="left_mid"),
                StudyVisualObject(id="p", kind="packet", label="Tool call", slot="center"),
                StudyVisualObject(id="t", kind="tool", label="API", slot="right_mid"),
            ],
            beats=[
                StudyVisualBeat(cue="1", action="reveal", target="a"),
                StudyVisualBeat(cue="2", action="reveal", target="t"),
                StudyVisualBeat(cue="3", action="connect", target="t", source="a", destination="t"),
                StudyVisualBeat(cue="4", action="highlight", target="p"),
            ],
        ),
    ]
    repaired, changed = StudyAnimationDirectorAgent._auto_repair_semantic_quality(
        broken, scenes, "AI Agents for Beginners"
    )
    from content_factory.visual.study_storyboard import storyboard_quality_report
    report = storyboard_quality_report(repaired)
    assert report["specialized_scene_pass_ratio"] == 1.0
    assert set(changed) == {4, 20}


class BatchFailsSingleSucceedsLLM(FakeStoryboardLLM):
    async def generate_structured(self, prompt, response_model, **kwargs):
        data = json.loads(prompt.split("SCENES:\n", 1)[1].split("\n\nNON-NEGOTIABLE", 1)[0])
        if len(data) > 1:
            raise ValueError("simulated truncated batch JSON")
        return await super().generate_structured(prompt, response_model, **kwargs)


@pytest.mark.asyncio
async def test_animation_director_rescues_failed_batch_per_scene(tmp_path: Path):
    scenes = [
        _scene(1, "Architecture", "The host sends a JSON-RPC request to an MCP server and tool."),
        _scene(2, "Implementation", "Implement the agent loop in code and verify the result."),
    ]
    state = WorkflowState(run_id="rescue", topic="Model Context Protocol MCP")
    state.metadata["content_mode"] = "study"
    state.production_plan = ContentProductionPlan(
        title="MCP",
        voice_segments=[
            VoiceSegment(id=1, text="a", estimated_duration_seconds=10),
            VoiceSegment(id=2, text="b", estimated_duration_seconds=10),
        ],
        visual_scenes=scenes,
        thumbnail_prompt="thumb",
        youtube_description="desc",
        youtube_tags=["mcp"],
    )
    result = await StudyAnimationDirectorAgent(
        BatchFailsSingleSucceedsLLM(), output_root=str(tmp_path)
    ).execute(state)
    assert result.metadata["study_storyboard_llm_rescued_scene_ids"] == [1, 2]
    assert result.metadata["study_storyboard_deterministic_scene_ids"] == []


def test_sparse_viewer_interaction_is_semantic_and_configurable(monkeypatch):
    monkeypatch.setenv("STUDY_ACTIVE_CHECKS", "on")
    monkeypatch.setenv("STUDY_ACTIVE_CHECK_EVERY", "4")
    sb = StudySceneStoryboard(
        scene_id=4,
        purpose="Explain request routing",
        layout="left_to_right",
        objects=[
            StudyVisualObject(id="client", kind="client", label="Client", slot="left_mid"),
            StudyVisualObject(id="server", kind="server", label="Server", slot="right_mid"),
            StudyVisualObject(id="packet", kind="packet", label="Request", slot="center"),
        ],
        beats=[
            StudyVisualBeat(cue="client", action="reveal", target="client"),
            StudyVisualBeat(cue="server", action="reveal", target="server"),
            StudyVisualBeat(cue="request", action="send", target="packet", source="client", destination="server"),
            StudyVisualBeat(cue="result", action="highlight", target="server"),
        ],
    )
    repaired = StudyAnimationDirectorAgent._repair_viewer_interaction(sb)
    assert repaired.interaction_style == "predict"
    assert repaired.interaction_prompt == "Where does Client send it?"
    assert repaired.interaction_answer == "Server"
    assert repaired.interaction_choices[0] == "Server"

    no_quiz = StudyAnimationDirectorAgent._repair_viewer_interaction(sb.model_copy(update={"scene_id": 5}))
    assert no_quiz.interaction_prompt is None


def test_viewer_interactions_are_off_by_default(monkeypatch):
    monkeypatch.delenv("STUDY_ACTIVE_CHECKS", raising=False)
    sb = StudySceneStoryboard(
        scene_id=4, purpose="Explain request routing", layout="left_to_right",
        objects=[
            StudyVisualObject(id="client", kind="client", label="Client", slot="left_mid"),
            StudyVisualObject(id="server", kind="server", label="Server", slot="right_mid"),
            StudyVisualObject(id="packet", kind="packet", label="Request", slot="center"),
        ],
        beats=[
            StudyVisualBeat(cue="client", action="reveal", target="client"),
            StudyVisualBeat(cue="server", action="reveal", target="server"),
            StudyVisualBeat(cue="request", action="send", target="packet", source="client", destination="server"),
            StudyVisualBeat(cue="result", action="highlight", target="server"),
        ],
        interaction_prompt="Old cached question", interaction_answer="Server",
        interaction_choices=["Server"], interaction_style="predict",
    )
    repaired = StudyAnimationDirectorAgent._repair_viewer_interaction(sb)
    assert repaired.interaction_prompt is None
    assert repaired.interaction_answer is None
    assert repaired.interaction_choices == []
    assert repaired.interaction_style is None


def test_theory_first_mandated_layouts_do_not_trigger_false_dominance_failure():
    """EXPLAIN/ FLOW repetition is pedagogical grammar, not template collapse."""
    from content_factory.visual.study_storyboard import storyboard_quality_report

    boards = []
    sid = 1
    for chapter in range(5):
        boards.append(StudySceneStoryboard(
            scene_id=sid,
            purpose=f"Explain chapter {chapter}",
            learning_phase="explain",
            chapter_title=f"Chapter {chapter}",
            layout="stack",
            teaching_pattern="concept_explain",
            objects=[
                StudyVisualObject(id="a", kind="theory_point", label="Definition", slot="wide_top", detail=["Definition point"]),
                StudyVisualObject(id="b", kind="theory_point", label="Key idea", slot="wide_mid", detail=["Key point"]),
                StudyVisualObject(id="c", kind="theory_point", label="Why it matters", slot="wide_bottom", detail=["Why point"]),
            ],
            beats=[
                StudyVisualBeat(cue="definition", action="reveal", target="a"),
                StudyVisualBeat(cue="key", action="reveal", target="b"),
                StudyVisualBeat(cue="why", action="reveal", target="c"),
                StudyVisualBeat(cue="remember", action="select", target="b"),
            ],
        ))
        sid += 1
        boards.append(StudySceneStoryboard(
            scene_id=sid,
            purpose=f"Flow chapter {chapter}",
            learning_phase="flow",
            chapter_title=f"Chapter {chapter}",
            layout="left_to_right",
            teaching_pattern="mechanism_flow",
            objects=[
                StudyVisualObject(id="a", kind="resource", label="Cause", slot="left_mid"),
                StudyVisualObject(id="b", kind="tool", label="Action", slot="center"),
                StudyVisualObject(id="c", kind="answer_panel", label="Result", slot="right_mid"),
            ],
            beats=[
                StudyVisualBeat(cue="cause", action="reveal", target="a"),
                StudyVisualBeat(cue="action", action="reveal", target="b"),
                StudyVisualBeat(cue="move", action="send", target="a", source="a", destination="b"),
                StudyVisualBeat(cue="result", action="send", target="b", source="b", destination="c"),
            ],
        ))
        sid += 1

    report = storyboard_quality_report(boards)
    assert report["raw_layout_dominance_ratio"] == 0.5
    assert report["layout_dominance_ratio"] == 0.0
    assert not any("one layout dominates" in issue for issue in report["issues"])
