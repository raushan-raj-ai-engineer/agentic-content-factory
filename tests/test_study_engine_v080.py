from __future__ import annotations

from content_factory.agents.study_animation_director import StudyAnimationDirectorAgent
from content_factory.models.content import VisualScene
from content_factory.visual.study_storyboard import (
    StudySceneStoryboard,
    StudyVisualBeat,
    StudyVisualObject,
    storyboard_quality_report,
)


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


def _base(sid: int = 1) -> StudySceneStoryboard:
    return StudySceneStoryboard(
        scene_id=sid,
        purpose="Teach the current operation",
        layout="left_to_right",
        objects=[
            StudyVisualObject(id="a", kind="document", label="Source", slot="left_mid"),
            StudyVisualObject(id="b", kind="array", label="Candidates", slot="center", detail=["A", "B", "C"]),
            StudyVisualObject(id="c", kind="resource", label="Result", slot="right_mid"),
        ],
        beats=[
            StudyVisualBeat(cue="show source", action="reveal", target="a"),
            StudyVisualBeat(cue="split source", action="split", target="b", source="a"),
            StudyVisualBeat(cue="scan candidates", action="scan", target="b"),
            StudyVisualBeat(cue="produce result", action="stream", target="c", source="b"),
        ],
        environment="document_space",
        camera_style="guided",
        motion_density="high",
    )


def test_v080_storyboard_accepts_premium_semantic_actions_and_motion_profile():
    board = _base()
    assert [beat.action for beat in board.beats] == ["reveal", "split", "scan", "stream"]
    assert board.environment == "document_space"
    assert board.camera_style == "guided"
    assert board.motion_density == "high"
    assert "document_space" in board.signature


def test_v080_new_semantic_actions_count_as_real_state_changes():
    quality = storyboard_quality_report([_base()])
    assert quality["dynamic_scene_ratio"] == 1.0
    assert quality["score"] >= 75


def test_v080_rag_chunking_uses_split_and_document_environment():
    scene = _scene(2, "Chunking", "Chunking splits a source document into smaller document chunks before retrieval.")
    fixed = StudyAnimationDirectorAgent._repair_topic_specific_teaching(
        _base(2), scene, "Retrieval-Augmented Generation RAG"
    )
    assert any(beat.action == "split" for beat in fixed.beats)
    assert fixed.environment == "document_space"
    assert fixed.camera_style == "guided"


def test_v080_rag_similarity_scans_before_selecting_match():
    scene = _scene(3, "Similarity search", "The query vector is compared by similarity search so retrieval selects the nearest chunk.")
    fixed = StudyAnimationDirectorAgent._repair_topic_specific_teaching(
        _base(3), scene, "RAG for beginners"
    )
    actions = [beat.action for beat in fixed.beats]
    assert "scan" in actions
    assert "select" in actions
    assert actions.index("scan") < actions.index("select")
    assert fixed.environment == "data_space"


def test_v080_rag_generation_streams_answer():
    scene = _scene(5, "Generation", "The language model uses retrieved context to generate a grounded answer from the source.")
    fixed = StudyAnimationDirectorAgent._repair_topic_specific_teaching(
        _base(5), scene, "RAG for beginners"
    )
    assert any(beat.action == "stream" for beat in fixed.beats)
    assert fixed.camera_style == "focus"
