from __future__ import annotations

from content_factory.agents.study_animation_director import StudyAnimationDirectorAgent
from content_factory.models.content import VisualScene
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


def _fix(sid: int, title: str, text: str) -> StudySceneStoryboard:
    return StudyAnimationDirectorAgent._repair_topic_specific_teaching(
        _generic(sid), _scene(sid, title, text), "Retrieval-Augmented Generation for beginners"
    )


def test_open_book_section_uses_literal_analogy_not_retriever_flowchart():
    fixed = _fix(
        8,
        "The Open-Book Exam Mental Model — 1",
        "Think of RAG like an open-book exam: you can look in the book before answering the question.",
    )
    kinds = {o.kind for o in fixed.objects}
    assert "book" in kinds
    assert "person" in kinds
    assert "vector_store" not in kinds
    assert all(o.label != "User Query" for o in fixed.objects)
    assert fixed.environment == "analogy_warm"


def test_architecture_chapter_has_three_distinct_visual_grammars():
    scenes = [
        _fix(11, "Step-by-Step System Architecture and Data Flow — 1", "Split the document into chunks, create embeddings, and store the vectors."),
        _fix(12, "Step-by-Step System Architecture and Data Flow — 2", "Turn the query into a vector and search for the most relevant chunk."),
        _fix(13, "Step-by-Step System Architecture and Data Flow — 3", "Add retrieved context, send it to the language model, and generate the answer from the source."),
    ]
    assert [s.layout for s in scenes] == ["left_to_right", "array_trace", "freeform"]
    third_kinds = {obj.kind for obj in scenes[2].objects}
    assert {"document", "search_ui", "context_window", "model", "answer_panel"} <= third_kinds
    assert any(beat.action == "merge" for beat in scenes[2].beats)
    assert any(o.kind == "point_cloud" for o in scenes[0].objects)
    assert any(o.kind == "search_ui" for o in scenes[1].objects)
    assert any(o.kind == "context_window" for o in scenes[2].objects)
    assert any(o.kind == "answer_panel" for o in scenes[2].objects)


def test_code_chapter_progresses_state_instead_of_repeating_same_snippet():
    descriptions = [
        "In Python, embed the query and search the vector store for documents.",
        "Join the retrieved documents and build the prompt context.",
        "Call the language model with the prompt and return the answer.",
        "Verify the answer is grounded in the retrieved documents.",
    ]
    boards = [
        _fix(14 + i, f"Translating the Architecture Into Code — {i + 1}", descriptions[i])
        for i in range(4)
    ]
    snippets = [tuple(next(o.detail for o in b.objects if o.kind == "code")) for b in boards]
    assert len(set(snippets)) == 4
    assert all(b.layout == "code_plus_state" for b in boards)
    assert any(o.kind == "point_cloud" for o in boards[0].objects)
    assert any(o.kind == "context_window" for o in boards[1].objects)
    assert any(o.kind == "answer_panel" for o in boards[2].objects)


def test_hook_uses_query_ui_and_cited_answer_panel():
    fixed = _fix(
        1,
        "Visualizing Retrieval-Augmented Generation for Beginners",
        "A user asks a question, the model retrieves private sources, and then gives a grounded answer.",
    )
    kinds = {o.kind for o in fixed.objects}
    assert {"search_ui", "document", "model", "answer_panel"} <= kinds
    assert fixed.layout == "browser_demo"
    assert any(b.action == "stream" for b in fixed.beats)
