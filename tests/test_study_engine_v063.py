from __future__ import annotations

from content_factory.agents.study_animation_director import StudyAnimationDirectorAgent
from content_factory.models.content import VisualScene
from content_factory.visual.study_storyboard import (
    StudySceneStoryboard,
    StudyVisualBeat,
    StudyVisualObject,
    diversity_report,
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


def _generic(sid: int) -> StudySceneStoryboard:
    return StudySceneStoryboard(
        scene_id=sid,
        purpose="generic",
        layout="left_to_right",
        objects=[
            StudyVisualObject(id="a", kind="client", label="A", slot="left_mid"),
            StudyVisualObject(id="b", kind="server", label="B", slot="center"),
            StudyVisualObject(id="c", kind="packet", label="C", slot="right_mid"),
        ],
        beats=[
            StudyVisualBeat(cue="one", action="reveal", target="a"),
            StudyVisualBeat(cue="two", action="reveal", target="b"),
            StudyVisualBeat(cue="three", action="connect", target="b", source="a", destination="b"),
            StudyVisualBeat(cue="four", action="send", target="c", source="a", destination="b"),
        ],
    )


def test_rag_hook_is_problem_solution_not_generic_flowchart():
    scene = _scene(
        1,
        "Why RAG matters",
        "A user asks a question. A language model needs private data to retrieve context and produce a grounded answer.",
    )
    fixed = StudyAnimationDirectorAgent._repair_topic_specific_teaching(
        _generic(1), scene, "RAG explained for beginners"
    )
    assert fixed.teaching_pattern == "problem_solution"
    assert {o.kind for o in fixed.objects} >= {"search_ui", "model", "document", "answer_panel"}
    assert {b.action for b in fixed.beats} >= {"send", "stream", "connect"}


def test_rag_chunking_physically_transforms_document_into_chunks():
    scene = _scene(
        2,
        "Chunking",
        "Chunking splits a source document into smaller document chunks before retrieval.",
    )
    fixed = StudyAnimationDirectorAgent._repair_topic_specific_teaching(
        _generic(2), scene, "Retrieval-Augmented Generation RAG"
    )
    assert fixed.teaching_pattern == "worked_example"
    assert any(o.kind == "array" and o.detail == ["Chunk 1", "Chunk 2", "Chunk 3"] for o in fixed.objects)
    assert any(b.action == "split" for b in fixed.beats)


def test_rag_similarity_scene_ranks_and_selects_nearest_chunk():
    scene = _scene(
        3,
        "Similarity search",
        "The query vector is compared by similarity search so retrieval selects the nearest chunk.",
    )
    fixed = StudyAnimationDirectorAgent._repair_topic_specific_teaching(
        _generic(3), scene, "RAG for beginners"
    )
    assert fixed.teaching_pattern == "retrieval_match"
    assert {b.action for b in fixed.beats} >= {"compare", "select", "move"}
    assert any(o.kind == "point_cloud" and o.label == "Semantic Matches" for o in fixed.objects)


def test_rag_context_build_combines_retrieved_context_before_model():
    scene = _scene(
        4,
        "Augmentation",
        "RAG adds retrieved context to the prompt before the language model generates an answer.",
    )
    fixed = StudyAnimationDirectorAgent._repair_topic_specific_teaching(
        _generic(4), scene, "RAG for beginners"
    )
    assert fixed.teaching_pattern == "context_build"
    assert any(o.kind == "context_window" and "Augmented" in o.label for o in fixed.objects)
    assert {b.action for b in fixed.beats} >= {"merge", "send"}


def test_rag_verification_uses_supported_and_unsupported_paths():
    scene = _scene(
        6,
        "Verify the answer",
        "Verify whether the grounded answer is faithful to evidence and reject hallucination.",
    )
    fixed = StudyAnimationDirectorAgent._repair_topic_specific_teaching(
        _generic(6), scene, "RAG for beginners"
    )
    assert fixed.teaching_pattern == "verification"
    assert fixed.layout == "boundary"
    assert {b.action for b in fixed.beats} >= {"allow", "reject", "compare"}


def test_rag_recap_is_topic_specific_and_has_no_execution_loop():
    scene = _scene(
        10,
        "Recap",
        "Recap the query, retrieve context, augment the prompt, generate the answer, and verify it.",
    )
    fixed = StudyAnimationDirectorAgent._repair_topic_specific_teaching(
        _generic(10), scene, "RAG for beginners"
    )
    assert fixed.teaching_pattern == "recap"
    assert [o.label for o in fixed.objects] == ["Query", "Retrieve", "Augment", "Generate", "Verify"]
    assert all(o.label != "Execution Loop" for o in fixed.objects)


def test_rag_interaction_is_specific_with_choices(monkeypatch):
    monkeypatch.setenv("STUDY_ACTIVE_CHECKS", "on")
    monkeypatch.setenv("STUDY_ACTIVE_CHECK_EVERY", "3")
    scene = _scene(
        3,
        "Similarity search",
        "The query vector uses similarity search to retrieve the nearest chunk.",
    )
    fixed = StudyAnimationDirectorAgent._repair_topic_specific_teaching(
        _generic(3), scene, "RAG for beginners"
    )
    checked = StudyAnimationDirectorAgent._repair_viewer_interaction(
        fixed, narration=scene.description, topic="RAG for beginners"
    )
    assert checked.interaction_prompt == "Which result should retrieval choose?"
    assert checked.interaction_answer == "Nearest Chunk"
    assert checked.interaction_choices == ["Nearest Chunk", "Random Chunk", "Largest File"]


def test_diversity_report_flags_near_clone_adjacent_scenes():
    report = diversity_report([_generic(1), _generic(2), _generic(3)])
    assert report["max_layout_run"] == 3
    assert report["high_similarity_pairs"] == [[1, 2], [2, 3]]


def test_cross_scene_repair_breaks_three_scene_layout_streak():
    repaired = StudyAnimationDirectorAgent._repair_cross_scene_repetition(
        [_generic(1), _generic(2), _generic(3)]
    )
    report = diversity_report(repaired)
    assert report["max_layout_run"] <= 2
