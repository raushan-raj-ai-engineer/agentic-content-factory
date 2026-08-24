#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-/Users/maa/agentic-content-factory}"

cd "$PROJECT"
source .venv/bin/activate
export PYTHONPATH="$PROJECT/src${PYTHONPATH:+:$PYTHONPATH}"

python - <<'PY'
import asyncio

from content_factory.cartoon.language import (
    load_language_pack,
)
from content_factory.cartoon.models import (
    CartoonEpisodeOutline,
    CartoonSceneBatch,
    CartoonSceneBrief,
    CartoonScene,
    CartoonDialogueLine,
)
from content_factory.cartoon.story_planner import (
    CartoonStoryPlanner,
)


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
        self.calls.append(
            response_model.__name__
        )

        if response_model is CartoonEpisodeOutline:
            briefs = []

            for i in range(1, 13):
                briefs.append(
                    CartoonSceneBrief(
                        id=i,
                        location_id="courtyard",
                        beat=(
                            "setup"
                            if i <= 2
                            else "punchline"
                            if i == 12
                            else "escalation"
                        ),
                        summary=f"Brief {i}",
                        speakers=[
                            "guddu",
                            "chacha",
                        ],
                        comedy_goal=f"Goal {i}",
                    )
                )

            return CartoonEpisodeOutline(
                title="Test",
                premise="Test premise",
                characters=[
                    "guddu",
                    "chacha",
                ],
                scene_briefs=briefs,
                ending_callback="Callback",
            )

        if response_model is CartoonSceneBatch:
            # Extract expected IDs from prompt; planner prints briefs in JSON.
            import re
            ids = [
                int(value)
                for value in re.findall(
                    r'"id":\s*(\d+)',
                    prompt,
                )
            ]

            # Deduplicate while preserving order.
            seen = []
            for value in ids:
                if value not in seen:
                    seen.append(value)

            scenes = []

            for i in seen:
                scenes.append(
                    CartoonScene(
                        id=i,
                        location_id="courtyard",
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
                                character_id="guddu",
                                text="टेस्ट संवाद",
                                emotion="neutral",
                            ),
                            CartoonDialogueLine(
                                character_id="chacha",
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

        raise AssertionError(
            response_model
        )


async def main():
    fake = FakeLLM()

    planner = CartoonStoryPlanner(
        fake
    )

    plan = await planner.create_plan(
        topic="Indian parents vs career choice",
        language=load_language_pack(
            "hindi"
        ),
        target_minutes=3,
        cast=[
            "guddu",
            "bittu",
            "chacha",
            "mai",
        ],
    )

    assert len(plan.scenes) == 12
    assert fake.calls[0] == "CartoonEpisodeOutline"
    assert fake.calls.count(
        "CartoonSceneBatch"
    ) == 4
    assert len(fake.calls) == 5

    print("3-minute target -> 12 scenes: OK")
    print("1 compact outline call: OK")
    print("4 x 3-scene batch calls: OK")
    print("Sequential plan assembly: OK")


asyncio.run(
    main()
)

print()
print("CARTOON GENERATION V9.0.1 TESTS PASSED")
PY
