#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

cd "$PROJECT"
source .venv/bin/activate
export PYTHONPATH="$PROJECT/src${PYTHONPATH:+:$PYTHONPATH}"

python - <<'PY'
import asyncio
import re

from content_factory.cartoon.characters import (
    background_ids,
    character_registry,
)
from content_factory.cartoon.language import (
    available_languages,
    load_language_pack,
)
from content_factory.cartoon.models import (
    CartoonDialogueLine,
    CartoonReaction,
    CartoonScene,
    CartoonSceneBatch,
)
from content_factory.cartoon.story_planner import (
    CartoonStoryPlanner,
)


expected_languages = {
    "english",
    "hindi",
    "hinglish",
    "magahi",
    "bhojpuri",
}
assert expected_languages.issubset(
    set(available_languages())
)
print("Cumulative language packs: OK")

registry = character_registry()
for character_id in (
    "guddu",
    "bittu",
    "chacha",
    "mai",
    "babuji",
):
    assert character_id in registry
print("Persistent original character registry: OK")

assert {
    "living_room",
    "office",
    "tea_shop",
    "courtyard",
}.issubset(set(background_ids()))
print("Reusable background registry: OK")


def parse_context(prompt):
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
    speakers = re.findall(
        r'"speakers":\s*\[\s*"([^"]+)",\s*"([^"]+)"\s*\]',
        prompt,
    )
    return ids[:3], locations[:3], beats[:3], speakers[:3]


class ContractDriftFakeLLM:
    def __init__(self):
        self.calls = 0
        self.attempts = {}

    async def generate_structured(
        self,
        prompt,
        response_model,
        *,
        system_prompt=None,
        max_retries=1,
    ):
        self.calls += 1
        ids, locations, beats, speaker_groups = parse_context(prompt)

        key = tuple(ids)
        attempt = self.attempts.get(key, 0)
        self.attempts[key] = attempt + 1

        scenes = []

        for index, scene_id in enumerate(ids):
            first, second = speaker_groups[index]

            if attempt == 0:
                # Force quality repair.
                dialogue = [
                    CartoonDialogueLine(
                        character_id=first,
                        text="मैं यही बात फिर से कह रहा हूँ क्योंकि मेरा फैसला वही है।",
                        emotion="neutral",
                        pose="idle",
                    ),
                    CartoonDialogueLine(
                        character_id=second,
                        text="तुम वही बात बार-बार कह रहे हो और जवाब भी वही है।",
                        emotion="neutral",
                        pose="idle",
                    ),
                    CartoonDialogueLine(
                        character_id=first,
                        text="मैं यही बात फिर से कह रहा हूँ क्योंकि मेरा फैसला वही है।",
                        emotion="neutral",
                        pose="idle",
                    ),
                ]
                location = locations[index]
                beat = beats[index]
                reaction = None
            else:
                # Simulate real repair drift: wrong location/beat/speakers.
                dialogue = [
                    CartoonDialogueLine(
                        character_id="babuji",
                        text=f"दृश्य {scene_id} में अब मैं नया कदम उठा रहा हूँ।",
                        emotion="smirk",
                        pose="thinking",
                    ),
                    CartoonDialogueLine(
                        character_id="chacha",
                        text=f"दृश्य {scene_id} में इस कदम का अलग जवाब है।",
                        emotion="angry",
                        pose="pointing",
                    ),
                    CartoonDialogueLine(
                        character_id="babuji",
                        text=f"दृश्य {scene_id} का परिणाम कहानी को आगे ले जाएगा।",
                        emotion="happy",
                        pose="thinking",
                    ),
                ]
                location = "home"
                beat = "setup"
                reaction = CartoonReaction(
                    character_id="babuji",
                    expression="shocked",
                    duration_seconds=0.7,
                    camera="reaction_close_up",
                    sfx="comic_sting",
                )

            scenes.append(
                CartoonScene(
                    id=scene_id,
                    location_id=location,
                    beat=beat,
                    camera="medium_two_shot",
                    shot_duration_seconds=6,
                    setup=f"Scene {scene_id}",
                    dialogue=dialogue,
                    reaction=reaction,
                    sfx_cues=[],
                    camera_action="static",
                    transition="hard_cut",
                )
            )

        return CartoonSceneBatch(scenes=scenes)


async def main():
    fake = ContractDriftFakeLLM()
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

    assert len(plan.scenes) == 9
    assert fake.calls == 6

    briefs = planner._build_scene_briefs(
        topic="Indian parents vs career choice",
        cast_ids=cast,
        scene_target=9,
    )
    brief_by_id = {
        brief.id: brief
        for brief in briefs
    }

    for scene in plan.scenes:
        brief = brief_by_id[scene.id]
        assert scene.location_id == brief.location_id
        assert scene.beat == brief.beat
        assert all(
            line.character_id in brief.speakers
            for line in scene.dialogue
        )
        if scene.reaction is not None:
            assert scene.reaction.character_id in brief.speakers

    assert sum(
        scene.shot_duration_seconds
        for scene in plan.scenes
    ) == 180.0

    print("V9.0.3 no-outline performance architecture: OK")
    print("V9.0.4 anti-repetition focused repair: OK")
    print("V9.0.4.3 brief location/beat contract: OK")
    print("V9.0.4.3 planned-speaker contract: OK")
    print("3-minute 180s story budget: OK")


asyncio.run(main())

print()
print("CARTOON RECOVERY V9.0.4.5 TESTS PASSED")
PY
