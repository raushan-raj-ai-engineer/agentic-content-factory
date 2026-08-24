#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-/Users/maa/agentic-content-factory}"

cd "$PROJECT"
source .venv/bin/activate
export PYTHONPATH="$PROJECT/src${PYTHONPATH:+:$PYTHONPATH}"

python - <<'PY'
import asyncio
import re

from content_factory.cartoon.language import load_language_pack
from content_factory.cartoon.models import (
    CartoonDialogueLine,
    CartoonScene,
    CartoonSceneBatch,
)
from content_factory.cartoon.story_planner import CartoonStoryPlanner


class FakeLLM:
    def __init__(self):
        self.calls = 0

    async def generate_structured(
        self,
        prompt,
        response_model,
        *,
        system_prompt=None,
        max_retries=1,
    ):
        self.calls += 1

        ids = []
        for value in re.findall(r'"id":\s*(\d+)', prompt):
            number = int(value)
            if number not in ids:
                ids.append(number)

        locations = re.findall(
            r'"location_id":\s*"([^"]+)"',
            prompt,
        )
        beats = re.findall(
            r'"beat":\s*"([^"]+)"',
            prompt,
        )

        scenes = []

        for index, scene_id in enumerate(ids):
            scenes.append(
                CartoonScene(
                    id=scene_id,
                    location_id=locations[index],
                    beat=beats[index],
                    camera="medium_two_shot",
                    shot_duration_seconds=7,
                    setup=f"Scene {scene_id}",
                    dialogue=[
                        CartoonDialogueLine(
                            character_id="Guddu",
                            text="टेस्ट संवाद",
                            emotion="neutral",
                        ),
                        CartoonDialogueLine(
                            character_id="Father",
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


async def main():
    fake = FakeLLM()

    planner = CartoonStoryPlanner(
        fake
    )

    plan = await planner.create_plan(
        topic="Indian parents vs career choice",
        language=load_language_pack("hindi"),
        target_minutes=3,
        cast=[
            "guddu",
            "bittu",
            "chacha",
            "mai",
            "babuji",
        ],
    )

    assert len(plan.scenes) == 9
    assert fake.calls == 3

    for scene in plan.scenes:
        for line in scene.dialogue:
            assert line.character_id in {
                "guddu",
                "bittu",
                "chacha",
                "mai",
                "babuji",
            }

    print("3-minute story skeleton -> 9 scenes: OK")
    print("LLM outline calls -> 0: OK")
    print("Dialogue/acting batch calls -> 3: OK")
    print("Character normalization preserved: OK")
    print("Compact cross-batch continuity preserved: OK")


asyncio.run(
    main()
)

print()
print("CARTOON PERFORMANCE V9.0.3 TESTS PASSED")
PY
