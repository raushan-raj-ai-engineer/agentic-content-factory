import pytest
from pydantic import ValidationError

from content_factory.models.content import (
    ContentProductionPlan,
    VisualScene,
    VoiceSegment,
)


def _voice_segments() -> list[VoiceSegment]:
    return [
        VoiceSegment(
            id=1,
            text="Introduction to the topic.",
            estimated_duration_seconds=10,
        ),
        VoiceSegment(
            id=2,
            text="Main explanation of the topic.",
            estimated_duration_seconds=20,
        ),
    ]


def _visual_scenes() -> list[VisualScene]:
    return [
        VisualScene(
            id=1,
            title="Introduction",
            description="Opening visual.",
            visual_type="talking_head",
            voice_segment_id=1,
            subject="AI software testing",
            key_elements=[
                "AI agent",
                "software testing",
                "test automation",
            ],
            composition=(
                "Central AI testing concept with a professional "
                "software engineering environment."
            ),
            style="Professional technical YouTube visual.",
        ),
        VisualScene(
            id=2,
            title="Main Explanation",
            description="Technical explanation visual.",
            visual_type="architecture_diagram",
            voice_segment_id=2,
            subject="AI testing architecture",
            key_elements=[
                "AI agent",
                "Playwright",
                "API testing",
                "application under test",
            ],
            composition=(
                "Layered architecture showing the AI agent "
                "interacting with testing tools and the application."
            ),
            style="Clean professional technical infographic.",
        ),
    ]


def _create_plan(
    voice_segments: list[VoiceSegment],
    visual_scenes: list[VisualScene],
) -> ContentProductionPlan:
    return ContentProductionPlan(
        title="Test Video",
        voice_segments=voice_segments,
        visual_scenes=visual_scenes,
        thumbnail_prompt="Professional technical YouTube thumbnail.",
        youtube_description="Test video description.",
        youtube_tags=["python", "automation"],
    )


def test_valid_production_plan_is_accepted() -> None:
    plan = _create_plan(
        _voice_segments(),
        _visual_scenes(),
    )

    assert len(plan.voice_segments) == 2
    assert len(plan.visual_scenes) == 2


def test_invalid_voice_segment_reference_is_rejected() -> None:
    scenes = _visual_scenes()

    scenes[1] = VisualScene(
        id=2,
        title="Invalid Scene",
        description="References a non-existent voice segment.",
        visual_type="code",
        voice_segment_id=99,
        subject="Invalid voice segment",
        key_elements=["code", "test automation"],
        composition="Code-focused technical scene.",
        style="Professional technical visual.",
    )

    with pytest.raises(ValidationError):
        _create_plan(
            _voice_segments(),
            scenes,
        )


def test_duplicate_voice_segment_reference_is_rejected() -> None:
    scenes = _visual_scenes()

    scenes[1] = VisualScene(
        id=2,
        title="Duplicate Mapping",
        description="References the first voice segment.",
        visual_type="code",
        voice_segment_id=1,
        subject="Python test automation",
        key_elements=[
            "Python",
            "test code",
            "automation",
        ],
        composition="Code-focused software testing scene.",
        style="Professional technical visual.",
    )

    with pytest.raises(ValidationError):
        _create_plan(
            _voice_segments(),
            scenes,
        )


def test_missing_visual_scene_is_rejected() -> None:
    scenes = _visual_scenes()[:1]

    with pytest.raises(ValidationError):
        _create_plan(
            _voice_segments(),
            scenes,
        )


def test_production_plan_requires_matching_voice_and_visual_counts() -> None:
    with pytest.raises(
        ValidationError,
        match="counts must match",
    ):
        ContentProductionPlan(
            title="Test Video",
            voice_segments=[
                VoiceSegment(
                    id=1,
                    text="First segment",
                    estimated_duration_seconds=30,
                ),
                VoiceSegment(
                    id=2,
                    text="Second segment",
                    estimated_duration_seconds=30,
                ),
            ],
            visual_scenes=[
                VisualScene(
                    id=1,
                    title="First Scene",
                    description="First visual",
                    visual_type="talking_head",
                    voice_segment_id=1,
                    subject="AI testing",
                    key_elements=[
                        "AI agent",
                        "testing",
                    ],
                    composition="Central AI testing concept.",
                    style="Professional technical visual.",
                ),
            ],
            thumbnail_prompt="Technical YouTube thumbnail",
            youtube_description="Test description",
            youtube_tags=["SDET"],
        )


def test_production_plan_accepts_one_visual_per_voice_segment() -> None:
    plan = ContentProductionPlan(
        title="Test Video",
        voice_segments=[
            VoiceSegment(
                id=1,
                text="First segment",
                estimated_duration_seconds=30,
            ),
            VoiceSegment(
                id=2,
                text="Second segment",
                estimated_duration_seconds=30,
            ),
        ],
        visual_scenes=[
            VisualScene(
                id=1,
                title="First Scene",
                description="First visual",
                visual_type="talking_head",
                voice_segment_id=1,
                subject="AI software testing",
                key_elements=[
                    "AI agent",
                    "test automation",
                ],
                composition="Central AI testing concept.",
                style="Professional technical visual.",
            ),
            VisualScene(
                id=2,
                title="Second Scene",
                description="Second visual",
                visual_type="architecture_diagram",
                voice_segment_id=2,
                subject="AI testing architecture",
                key_elements=[
                    "AI agent",
                    "Playwright",
                    "API",
                ],
                composition="Layered AI testing architecture.",
                style="Clean technical infographic.",
            ),
        ],
        thumbnail_prompt="Technical YouTube thumbnail",
        youtube_description="Test description",
        youtube_tags=["SDET"],
    )

    assert len(plan.voice_segments) == len(plan.visual_scenes)
