from types import SimpleNamespace

from content_factory.agents.study_animation_director import StudyAnimationDirectorAgent
from content_factory.visual.study_storyboard import StudySceneStoryboard, StudyVisualBeat, StudyVisualObject


def _base():
    return StudySceneStoryboard(
        scene_id=2,
        purpose="Explain AI agents",
        layout="left_to_right",
        objects=[
            StudyVisualObject(id="agent", kind="agent", label="AI Agent", slot="left_mid"),
            StudyVisualObject(id="tool", kind="tool", label="Tool", slot="center"),
            StudyVisualObject(id="result", kind="resource", label="Result", slot="right_mid"),
        ],
        beats=[
            StudyVisualBeat(cue="agent", action="reveal", target="agent"),
            StudyVisualBeat(cue="tool", action="reveal", target="tool"),
            StudyVisualBeat(cue="result", action="reveal", target="result"),
            StudyVisualBeat(cue="done", action="select", target="result"),
        ],
    )


def test_explain_scene_becomes_voice_grounded_theory_points():
    scene = SimpleNamespace(
        id=2,
        learning_phase="explain",
        chapter_title="AI Agents",
        title="AI Agents",
        description=(
            "An AI agent works toward a goal. "
            "It can choose actions or tools based on the current situation. "
            "This matters because multi-step work can continue without a new prompt for every step."
        ),
    )
    fixed = StudyAnimationDirectorAgent._repair_beginner_pedagogy(_base(), scene, "AI Agents")
    assert fixed.layout == "stack"
    assert fixed.camera_style == "static"
    assert fixed.motion_density == "low"
    assert [obj.kind for obj in fixed.objects] == ["theory_point", "theory_point", "theory_point"]
    assert [obj.label for obj in fixed.objects] == ["Definition", "Key idea", "Why it matters"]
    spoken = " ".join(scene.description.lower().split())
    for obj in fixed.objects:
        assert obj.detail
        point = " ".join(obj.detail[0].lower().split()).rstrip(".")
        assert point[:24] in spoken or any(word in spoken for word in point.split()[:3])


def test_flow_still_follows_theory_in_next_window():
    scene = SimpleNamespace(
        id=3,
        learning_phase="flow",
        chapter_title="AI Agents",
        title="AI Agents",
        description="The goal enters the agent, the agent selects a tool, the tool returns an observation, and the agent decides the next action.",
    )
    fixed = StudyAnimationDirectorAgent._repair_beginner_pedagogy(_base(), scene, "AI Agents")
    assert fixed.learning_phase == "flow"
    assert fixed.layout == "left_to_right"
    assert fixed.camera_style == "follow"
    assert fixed.teaching_pattern == "mechanism_flow"
