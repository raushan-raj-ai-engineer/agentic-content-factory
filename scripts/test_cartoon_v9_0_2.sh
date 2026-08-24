#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-/Users/maa/agentic-content-factory}"

cd "$PROJECT"
source .venv/bin/activate
export PYTHONPATH="$PROJECT/src${PYTHONPATH:+:$PYTHONPATH}"

python - <<'PY'
import asyncio

from content_factory.cartoon.language import load_language_pack
from content_factory.cartoon.models import (
    CartoonDialogueLine,
    CartoonEpisodeOutline,
    CartoonScene,
    CartoonSceneBatch,
    CartoonSceneBrief,
)
from content_factory.cartoon.story_planner import CartoonStoryPlanner


class FakeLLM:
    def __init__(self):
        self.calls = []

    async def generate_structured(
        self,
        prompt,
        response_model,
        *,
        system_prompt=None,
        max_retries=0,
    ):
        self.calls.append(response_model.__name__)

        if response_model is CartoonEpisodeOutline:
            speaker_variants = [
                ["Guddu", "Chacha"],
                ["गुड्डू", "माँ"],
                ["Bittu", "Guddu"],
                ["Father", "Guddu"],   # exact observed class of failure
                ["Mai", "Babuji"],
                ["uncle", "Guddu"],
                ["friend", "Guddu"],
                ["Mother", "Guddu"],
                ["पिताजी", "Guddu"],
                ["Chacha", "Bittu"],
                ["Guddu", "Mai"],
                ["Babuji", "Guddu"],
            ]

            briefs = [
                CartoonSceneBrief(
                    id=i,
                    location_id=(
                        "tea shop"
                        if i == 4
                        else "courtyard"
                    ),
                    beat=(
                        "setup"
                        if i <= 2
                        else "punchline"
                        if i == 12
                        else "escalation"
                    ),
                    summary=f"Brief {i}",
                    speakers=speaker_variants[i - 1],
                    comedy_goal=f"Goal {i}",
                )
                for i in range(1, 13)
            ]

            return CartoonEpisodeOutline(
                title="Test",
                premise="Parents and career comedy",
                characters=[
                    "Guddu",
                    "Bittu",
                    "Chacha",
                    "Mai",
                    "Babuji",
                ],
                scene_briefs=briefs,
                ending_callback="Callback",
            )

        if response_model is CartoonSceneBatch:
            import re

            ids = []
            for value in re.findall(r'"id":\s*(\d+)', prompt):
                number = int(value)
                if number not in ids:
                    ids.append(number)

            scenes = []

            for i in ids:
                scenes.append(
                    CartoonScene(
                        id=i,
                        location_id=(
                            "tea shop"
                            if i == 4
                            else "courtyard"
                        ),
                        beat=(
                            "setup"
                            if i <= 2
                            else "punchline"
                            if i == 12
                            else "escalation"
                        ),
                        camera="medium_two_shot",
                        shot_duration_seconds=7,
                        setup=f"Scene {i}",
                        dialogue=[
                            CartoonDialogueLine(
                                character_id="Guddu",
                                text="टेस्ट संवाद",
                                emotion="neutral",
                            ),
                            CartoonDialogueLine(
                                character_id=(
                                    "Father"
                                    if i == 4
                                    else "Chacha"
                                ),
                                text="दूसरा संवाद",
                                emotion="angry",
                            ),
                        ],
                        reaction=None,
                        sfx_cues=[],
                        camera_action="static",
                        transition="hard_cut",
                    )
                )

            return CartoonSceneBatch(
                scenes=scenes
            )

        raise AssertionError(response_model)


async def main():
    fake = FakeLLM()
    planner = CartoonStoryPlanner(fake)

    cast = [
        "guddu",
        "bittu",
        "chacha",
        "mai",
        "babuji",
    ]

    plan = await planner.create_plan(
        topic="Indian parents vs career choice",
        language=load_language_pack("hindi"),
        target_minutes=3,
        cast=cast,
    )

    assert len(plan.scenes) == 12
    assert plan.characters == cast

    for scene in plan.scenes:
        assert scene.location_id in {
            "courtyard",
            "tea_shop",
        }

        for line in scene.dialogue:
            assert line.character_id in cast

    scene4 = plan.scenes[3]
    assert any(
        line.character_id == "babuji"
        for line in scene4.dialogue
    )

    assert len(fake.calls) == 5

    print("Display-name -> canonical character IDs: OK")
    print("Hindi/English role alias -> canonical IDs: OK")
    print("'Father' -> babuji normalization: OK")
    print("'tea shop' -> tea_shop normalization: OK")
    print("Outline + four 3-scene batches preserved: OK")


asyncio.run(main())

print()
print("CARTOON IDENTIFIER HOTFIX V9.0.2 TESTS PASSED")
PY
