from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


CameraType = Literal[
    "wide",
    "medium",
    "medium_two_shot",
    "close_up",
    "reaction_close_up",
    "over_shoulder",
    "cutaway",
]

EmotionType = Literal[
    "neutral",
    "happy",
    "smirk",
    "angry",
    "shocked",
    "confused",
    "embarrassed",
    "laughing",
    "serious",
    "suspicious",
    "proud",
    "sad",
    "excited",
]

BeatType = Literal[
    "setup",
    "escalation",
    "misdirection",
    "reaction",
    "punchline",
    "callback",
    "transition",
]


class CartoonDialogueLine(BaseModel):
    character_id: str
    text: str = Field(min_length=1, max_length=500)
    emotion: EmotionType = "neutral"
    pose: str = "idle"
    pause_after_seconds: float = Field(default=0.15, ge=0.0, le=2.0)


class CartoonReaction(BaseModel):
    character_id: str
    expression: EmotionType
    duration_seconds: float = Field(default=0.6, ge=0.15, le=3.0)
    camera: CameraType = "reaction_close_up"
    sfx: str | None = None


class CartoonScene(BaseModel):
    id: int = Field(ge=1)
    location_id: str
    beat: BeatType
    camera: CameraType
    shot_duration_seconds: float = Field(default=6.0, ge=2.0, le=20.0)
    setup: str = Field(min_length=1, max_length=500)
    dialogue: list[CartoonDialogueLine] = Field(min_length=1, max_length=8)
    reaction: CartoonReaction | None = None
    sfx_cues: list[str] = Field(default_factory=list, max_length=5)
    camera_action: str = "static"
    transition: str = "hard_cut"
    visual_characters: list[str] = Field(default_factory=list, max_length=5)
    visual_action: str = "auto"
    props: list[str] = Field(default_factory=list, max_length=6)
    capability_world: str = "auto"
    capability_fallback: bool = False
    # V11.2 topic-agnostic scene-environment metadata. These defaults keep
    # older saved episode plans fully compatible.
    continuity_group: str = ""
    location_changed: bool = False
    environment_variant: str = "auto"
    environment_motion: str = "auto"
    # V11.4 scene staging contract. "auto" preserves older saved plans.
    blocking_mode: str = "auto"


class CartoonEpisodePlan(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    topic: str = Field(min_length=1)
    language_code: str
    language_name: str
    genre: str = "general_comedy"
    route: str = "general_comedy"
    audience: str = "all"
    story_tags: list[str] = Field(default_factory=list, max_length=12)
    premise: str = Field(min_length=1, max_length=800)
    characters: list[str] = Field(min_length=2, max_length=5)
    scenes: list[CartoonScene] = Field(min_length=4, max_length=24)
    ending_callback: str | None = None
    originality_note: str = (
        "Original characters, dialogue and scene construction; "
        "no copied creator/channel assets."
    )

    @model_validator(mode="after")
    def validate_scene_ids(self) -> "CartoonEpisodePlan":
        ids = [scene.id for scene in self.scenes]

        if ids != list(range(1, len(ids) + 1)):
            raise ValueError(
                "Scene IDs must be sequential starting at 1."
            )

        return self

class CartoonSceneBrief(BaseModel):
    id: int = Field(ge=1)
    location_id: str
    beat: BeatType
    summary: str = Field(min_length=1, max_length=500)
    speakers: list[str] = Field(min_length=1, max_length=4)
    comedy_goal: str = Field(min_length=1, max_length=300)
    # Deterministic scene direction survives both LLM and full local fallback.
    visual_action: str = "auto"
    camera_hint: CameraType = "medium_two_shot"
    camera_action_hint: str = "static"
    blocking_mode: str = "auto"
    props: list[str] = Field(default_factory=list, max_length=6)
    force_background_change: bool = False


class CartoonEpisodeOutline(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    premise: str = Field(min_length=1, max_length=800)
    characters: list[str] = Field(min_length=2, max_length=5)
    scene_briefs: list[CartoonSceneBrief] = Field(min_length=6, max_length=24)
    ending_callback: str | None = None


class CartoonSceneBatch(BaseModel):
    scenes: list[CartoonScene] = Field(min_length=1, max_length=8)

