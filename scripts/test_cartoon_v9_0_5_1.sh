#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

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


def context(prompt):
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
    return ids[:3], locations[:3], beats[:3]


class ChaosFakeLLM:
    def __init__(self):
        self.calls = 0

    async def generate_structured(
        self,
        prompt,
        response_model,
        *,
        system_prompt=None,
        max_retries=0,
    ):
        self.calls += 1
        ids, locations, beats = context(prompt)

        if self.calls == 2:
            raise RuntimeError("simulated Ollama timeout")

        if self.calls == 1:
            # Wrong location/speaker + repeated dialogue.
            scenes = []
            for scene_id in ids:
                scenes.append(
                    CartoonScene(
                        id=scene_id,
                        location_id="home",
                        beat="setup",
                        camera="wide",
                        shot_duration_seconds=6,
                        setup="weak scene",
                        dialogue=[
                            CartoonDialogueLine(
                                character_id="manager",
                                text="मैं यही बात फिर से कह रहा हूँ क्योंकि मेरा फैसला वही है।",
                            ),
                            CartoonDialogueLine(
                                character_id="manager",
                                text="तुम वही बात बार-बार कह रहे हो और जवाब भी वही है।",
                            ),
                            CartoonDialogueLine(
                                character_id="manager",
                                text="मैं यही बात फिर से कह रहा हूँ क्योंकि मेरा फैसला वही है।",
                            ),
                        ],
                        reaction=None,
                        sfx_cues=["bad sound"],
                        camera_action="static",
                        transition="hard_cut",
                    )
                )
            return CartoonSceneBatch(scenes=scenes)

        # Observed failure class: expected [7,8,9], actual [1,2,3,4].
        scenes = []
        for index in range(4):
            scenes.append(
                CartoonScene(
                    id=index + 1,
                    location_id="home",
                    beat="setup",
                    camera="wide",
                    shot_duration_seconds=6,
                    setup="wrong id scene",
                    dialogue=[
                        CartoonDialogueLine(
                            character_id="babuji",
                            text=f"दृश्य {index + 1} में अब नया कदम लिया जा रहा है।",
                            emotion="smirk",
                            pose="thinking",
                        ),
                        CartoonDialogueLine(
                            character_id="chacha",
                            text=f"दृश्य {index + 1} में इसका जवाब अलग है।",
                            emotion="angry",
                            pose="pointing",
                        ),
                        CartoonDialogueLine(
                            character_id="babuji",
                            text=f"दृश्य {index + 1} कहानी को आगे ले जाएगा।",
                            emotion="happy",
                            pose="thinking",
                        ),
                    ],
                    reaction=None,
                    sfx_cues=[],
                    camera_action="static",
                    transition="hard_cut",
                )
            )
        return CartoonSceneBatch(scenes=scenes)


async def main():
    fake = ChaosFakeLLM()
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

    assert fake.calls == 3
    assert len(plan.scenes) == 9
    assert [scene.id for scene in plan.scenes] == list(range(1, 10))
    assert sum(scene.shot_duration_seconds for scene in plan.scenes) == 180.0

    briefs = planner._build_scene_briefs(
        topic="Indian parents vs career choice",
        cast_ids=cast,
        scene_target=9,
    )

    for scene, brief in zip(plan.scenes, briefs):
        assert scene.id == brief.id
        assert scene.location_id == brief.location_id
        assert scene.beat == brief.beat
        assert all(
            line.character_id in brief.speakers
            for line in scene.dialogue
        )

    report = planner.last_report

    assert report["llm_quality_repair_calls"] == 0
    assert report["llm_batch_failures"] == 1
    assert report["fallback_scenes"] == 3
    assert report["dropped_extra_scenes"] == 1
    assert report["quality_local_repairs"] >= 1

    print("Exactly 3 LLM batch attempts: OK")
    print("LLM quality-repair calls = 0: OK")
    print("LLM timeout -> local batch fallback: OK")
    print("expected [7,8,9] / returned [1,2,3,4] -> reconciled: OK")
    print("extra scene -> safely dropped: OK")
    print("'home' -> planned location: OK")
    print("invented speaker -> planned speaker: OK")
    print("repeated dialogue -> local dialogue repair: OK")
    print("9 sequential scenes / 180s plan: OK")
    print("RECOVERABLE FAILURES DID NOT ABORT THE RUN: OK")


asyncio.run(main())

print()
print("CARTOON FAIL-SAFE V9.0.5.1 TESTS PASSED")
PY
