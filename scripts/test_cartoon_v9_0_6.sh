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
    speakers = re.findall(
        r'"speakers":\s*\[\s*"([^"]+)",\s*"([^"]+)"\s*\]',
        prompt,
    )

    return ids[:3], locations[:3], beats[:3], speakers[:3]


class SemanticDriftFakeLLM:
    """
    Structurally valid output with the exact real-world quality problems:
    generic/repeated setup, child-future drift, electricity drift, and an
    awkward future sentence. V9.0.6 must repair these locally without a fourth
    LLM call.
    """

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
        ids, locations, beats, speakers = context(prompt)

        bad_lines = {
            1: (
                "मैं वही रास्ता चुनना चाहता हूँ जिसमें अच्छा काम कर सकूँ।",
                "रास्ता चुनो, योजना भी दिखाओ।",
                "ठीक है, काम दिखाऊँगा।",
            ),
            2: (
                "मैं वही रास्ता चुनना चाहता हूँ जिसमें अच्छा काम कर सकूँ।",
                "रास्ता चुनो, योजना भी दिखाओ।",
                "ठीक है, काम दिखाऊँगा।",
            ),
            3: (
                "सबको बस सुरक्षित नौकरी क्यों दिखती है?",
                "कमाई भी जरूरी है।",
                "मेरी योजना देखिए।",
            ),
            4: (
                "अपने बच्चे के भविष्य के बारे में भी सोचो।",
                "मैं अपने बच्चे का भविष्य बना रहा हूँ।",
                "नौकरी ही भविष्य की गारंटी है।",
            ),
            5: (
                "यह बहुत अच्छा काम है और अच्छी आय देगा।",
                "यह बिजली की बर्बादी वाला सामान तो नहीं?",
                "बैटरी लगाकर देख लेते हैं।",
            ),
            6: (
                "मैं अपना काम दिखा रहा हूँ।",
                "सब ठीक है।",
                "चलो आगे देखते हैं।",
            ),
            7: (
                "मैं अपना भविष्य बन रहा हूँ।",
                "तुम मेरा भविष्य बना रहे हो।",
                "भविष्य खुद बनेगा।",
            ),
            8: (
                "अच्छा काम है।",
                "ठीक है।",
                "अब घर चलो।",
            ),
            9: (
                "मेहनत करूंगा।",
                "ठीक है।",
                "फिर देखेंगे।",
            ),
        }

        scenes = []

        for index, scene_id in enumerate(ids):
            first, second = speakers[index]
            d1, d2, d3 = bad_lines[scene_id]

            scenes.append(
                CartoonScene(
                    id=scene_id,
                    location_id=locations[index],
                    beat=beats[index],
                    camera="medium_two_shot",
                    shot_duration_seconds=6,
                    setup=f"Scene {scene_id}",
                    dialogue=[
                        CartoonDialogueLine(
                            character_id=first,
                            text=d1,
                            emotion="neutral",
                            pose="idle",
                        ),
                        CartoonDialogueLine(
                            character_id=second,
                            text=d2,
                            emotion="neutral",
                            pose="idle",
                        ),
                        CartoonDialogueLine(
                            character_id=first,
                            text=d3,
                            emotion="neutral",
                            pose="idle",
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
    fake = SemanticDriftFakeLLM()
    planner = CartoonStoryPlanner(fake)

    cast = [
        "guddu",
        "bittu",
        "chacha",
        "mai",
        "babuji",
    ]

    language = load_language_pack("hindi")

    plan = await planner.create_plan(
        topic="Indian parents vs career choice",
        language=language,
        target_minutes=3,
        cast=cast,
    )

    assert fake.calls == 3, fake.calls
    assert len(plan.scenes) == 9
    assert [scene.id for scene in plan.scenes] == list(range(1, 10))
    assert sum(scene.shot_duration_seconds for scene in plan.scenes) == 180.0

    assert "गेम डिजाइनर" in plan.premise
    assert "शर्मा जी" in plan.premise

    text_by_scene = {
        scene.id: " ".join(
            line.text
            for line in scene.dialogue
        )
        for scene in plan.scenes
    }

    assert "गेम डिजाइनर" in text_by_scene[1]
    assert any(token in text_by_scene[2] for token in ("कमाई", "स्थिरता", "छह महीने"))
    assert any(token in text_by_scene[3] for token in ("गेम", "डेमो", "मोबाइल"))
    assert any(token in text_by_scene[4] for token in ("सैलरी", "शर्मा", "तुलना", "कमाई"))
    assert any(token in text_by_scene[5] for token in ("गेम", "डेमो", "मोबाइल"))
    assert any(token in text_by_scene[6] for token in ("डेमो", "अटक", "बग"))
    assert any(token in text_by_scene[7] for token in ("काम", "मेहनत", "बनाया"))
    assert any(token in text_by_scene[8] for token in ("शर्मा", "तुलना", "इंजीनियर"))
    assert any(token in text_by_scene[9] for token in ("छह महीने", "कमाई", "मिठाई"))

    whole = " ".join(text_by_scene.values())

    for forbidden in (
        "बिजली",
        "बैटरी",
        "अपने बच्चे का भविष्य",
        "तुम्हारे बच्चे के भविष्य",
        "मैं अपना भविष्य बन रहा हूँ",
    ):
        assert forbidden not in whole, forbidden

    report = planner.last_report

    assert report["premise_key"] == "game_designer"
    assert report["llm_quality_repair_calls"] == 0
    assert report["normal_llm_batch_attempts"] == 3
    assert report["continuity_semantic_repairs"] >= 1
    assert report["quality_local_repairs"] >= 1

    print("Premise lock -> game_designer: OK")
    print("Same career/project/comparison across 9 scenes: OK")
    print("Scene-specific local repair dialogue: OK")
    print("Child-future drift removed: OK")
    print("Electricity/battery drift removed: OK")
    print("Awkward future drift removed: OK")
    print("Exactly 3 LLM batch attempts: OK")
    print("Extra LLM quality-repair calls = 0: OK")
    print("9 sequential scenes / 180s plan: OK")
    print("STORY CONTINUITY QUALITY LOCK: OK")


asyncio.run(main())

print()
print("CARTOON STORY LOCK V9.0.6 TESTS PASSED")
PY
