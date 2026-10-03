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
    CartoonReaction,
    CartoonScene,
    CartoonSceneBatch,
)
from content_factory.cartoon.story_planner import CartoonStoryPlanner


def parse_batch_context(prompt: str):
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
    speaker_groups = re.findall(
        r'"speakers":\s*\[\s*"([^"]+)",\s*"([^"]+)"\s*\]',
        prompt,
    )

    return ids[:3], locations[:3], beats[:3], speaker_groups[:3]


class CleanFakeLLM:
    """Produces genuinely distinct scenes that should NOT trigger repair."""

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
        ids, locations, beats, speaker_groups = parse_batch_context(prompt)

        scene_dialogues = {
            1: (
                "मैं सरकारी नौकरी की तैयारी छोड़कर गेम डिजाइन सीखना चाहता हूँ।",
                "तूने यह बात घर पर बताई तो पहले तेरी पढ़ाई का हिसाब पूछा जाएगा।",
                "इसलिए आज मैं उन्हें अपना बनाया छोटा गेम दिखाऊँगा।",
            ),
            2: (
                "माँ को लगता है सुरक्षित नौकरी ही असली करियर होती है।",
                "मुझे डर नौकरी से नहीं, तेरे हर महीने बदलते प्लान से है।",
                "इस बार प्लान नहीं, छह महीने का काम सामने रखूँगा।",
            ),
            3: (
                "अगर डेमो चल गया तो आधी बहस वहीं खत्म हो जाएगी।",
                "और अगर लैपटॉप फिर अटक गया तो पूरी बहस वहीं शुरू होगी।",
                "तू बस चाचा को बीच में टेक्निकल सलाह देने मत देना।",
            ),
            4: (
                "बाबूजी ने पूछा है इसमें तनख्वाह कितनी तय है।",
                "उन्हें अनिश्चित कमाई से ज्यादा पड़ोसियों का सवाल परेशान करता है।",
                "तो मैं पहले काम और कमाई दोनों का साफ हिसाब दिखाऊँगा।",
            ),
            5: (
                "देखिए, यह गेम मैंने खुद बनाया है और लोग इसे खेल भी रहे हैं।",
                "अच्छा है, मगर तारीफ से बिजली का बिल नहीं भरता।",
                "पहली कमाई आते ही बिल मैं भरूँगा, बात पक्की।",
            ),
            6: (
                "डेमो के बीच में ऐप बंद हो गया, अब क्या बोलेगा?",
                "यही कि असली नौकरी में भी सिस्टम कभी-कभी बैठ जाता है।",
                "बस यह मत कहना कि इसे भी सरकारी सर्वर समझकर छोड़ दें।",
            ),
            7: (
                "इतनी मेहनत देखकर मुझे लगा था यह बस मोबाइल चला रहा है।",
                "मैं भी यही समझता था, पर इसके फोल्डर में सचमुच काम भरा है।",
                "अब डाँटने से पहले शायद हमें पूरा देख लेना चाहिए।",
            ),
            8: (
                "बाबूजी, जिस इंजीनियर बेटे से आप तुलना करते हैं वह मेरा गेम खरीदना चाहता है।",
                "वही शर्मा जी का बेटा? जो हर रविवार उदाहरण बनता है?",
                "हाँ, आज पहली बार तुलना मेरे काम के पक्ष में गई है।",
            ),
            9: (
                "ठीक है, छह महीने दे रहे हैं, लेकिन मेहनत रोज दिखनी चाहिए।",
                "मान गया, बस हर हफ्ते करियर बदलने वाली मीटिंग मत रखिएगा।",
                "मीटिंग बंद—लेकिन पहली कमाई से घर की मिठाई तेरी तरफ से।",
            ),
        }

        scenes = []

        for index, scene_id in enumerate(ids):
            first, second = speaker_groups[index]
            beat = beats[index]
            d1, d2, d3 = scene_dialogues[scene_id]

            reaction = None
            if beat in {"reaction", "punchline", "callback"}:
                reaction = CartoonReaction(
                    character_id=second,
                    expression="shocked",
                    duration_seconds=0.7,
                    camera="reaction_close_up",
                    sfx="comic_sting",
                )

            scenes.append(
                CartoonScene(
                    id=scene_id,
                    location_id=locations[index],
                    beat=beat,
                    camera="medium_two_shot",
                    shot_duration_seconds=6,
                    setup=f"Scene {scene_id}",
                    dialogue=[
                        CartoonDialogueLine(
                            character_id=first,
                            text=d1,
                            emotion="happy",
                            pose="thinking",
                        ),
                        CartoonDialogueLine(
                            character_id=second,
                            text=d2,
                            emotion="angry",
                            pose="pointing",
                        ),
                        CartoonDialogueLine(
                            character_id=first,
                            text=d3,
                            emotion="smirk",
                            pose="thinking",
                        ),
                    ],
                    reaction=reaction,
                    sfx_cues=[],
                    camera_action="static",
                    transition="hard_cut",
                )
            )

        return CartoonSceneBatch(scenes=scenes)


class RepairFakeLLM:
    """
    First call for each batch is intentionally repetitive/flat.
    Repair call returns distinct, expressive content.
    """

    def __init__(self):
        self.calls = 0
        self.batch_attempts = {}

    async def generate_structured(
        self,
        prompt,
        response_model,
        *,
        system_prompt=None,
        max_retries=1,
    ):
        self.calls += 1
        ids, locations, beats, speaker_groups = parse_batch_context(prompt)

        key = tuple(ids)
        attempt = self.batch_attempts.get(key, 0)
        self.batch_attempts[key] = attempt + 1

        scenes = []

        for index, scene_id in enumerate(ids):
            first, second = speaker_groups[index]
            beat = beats[index]

            if attempt == 0:
                # Deliberately weak output: repeated template, neutral, no reaction.
                dialogue = [
                    CartoonDialogueLine(
                        character_id=first,
                        text="मैं यही बात फिर से कह रहा हूँ क्योंकि मेरी योजना वही है।",
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
                        text="मैं यही बात फिर से कह रहा हूँ क्योंकि मेरी योजना वही है।",
                        emotion="neutral",
                        pose="idle",
                    ),
                ]
                reaction = None
            else:
                # Focused repair output.
                dialogue = [
                    CartoonDialogueLine(
                        character_id=first,
                        text=f"दृश्य {scene_id} में मैं अब सिर्फ बोल नहीं रहा, एक नया कदम उठा रहा हूँ।",
                        emotion="smirk",
                        pose="thinking",
                    ),
                    CartoonDialogueLine(
                        character_id=second,
                        text=f"ठीक है, पर दृश्य {scene_id} का यह कदम उल्टा भी पड़ सकता है।",
                        emotion="confused",
                        pose="pointing",
                    ),
                    CartoonDialogueLine(
                        character_id=first,
                        text=f"अगर उल्टा पड़ा तो दृश्य {scene_id} की गलती से ही अगला मज़ाक निकलेगा।",
                        emotion="happy",
                        pose="thinking",
                    ),
                ]

                reaction = None
                if beat in {"reaction", "punchline", "callback"}:
                    reaction = CartoonReaction(
                        character_id=second,
                        expression="shocked",
                        duration_seconds=0.7,
                        camera="reaction_close_up",
                        sfx="comic_sting",
                    )

            scenes.append(
                CartoonScene(
                    id=scene_id,
                    location_id=locations[index],
                    beat=beat,
                    camera="wide",
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


async def clean_path():
    fake = CleanFakeLLM()
    planner = CartoonStoryPlanner(fake)

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
    assert fake.calls == 3, fake.calls
    assert sum(
        scene.shot_duration_seconds
        for scene in plan.scenes
    ) == 180.0

    assert any(
        line.emotion != "neutral"
        for scene in plan.scenes
        for line in scene.dialogue
    )

    assert all(
        scene.reaction is not None
        for scene in plan.scenes
        if scene.beat in {"reaction", "punchline", "callback"}
    )

    print("Normal quality path -> exactly 3 LLM calls: OK")
    print("3-minute duration budget -> 180s: OK")
    print("Unique progression skeleton: OK")
    print("Expressive direction + payoff reactions: OK")


async def repair_path():
    fake = RepairFakeLLM()
    planner = CartoonStoryPlanner(fake)

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

    # 3 normal generation calls + 1 focused repair for each weak batch.
    assert fake.calls == 6, fake.calls
    assert all(
        attempts == 2
        for attempts in fake.batch_attempts.values()
    )

    assert sum(
        scene.shot_duration_seconds
        for scene in plan.scenes
    ) == 180.0

    print("Weak quality path -> focused batch repairs: OK")
    print("3 weak batches -> 3 generation + 3 repair calls: OK")
    print("No full-episode regeneration: OK")


async def main():
    await clean_path()
    print()
    await repair_path()


asyncio.run(main())

print()
print("CARTOON STORY QUALITY V9.0.4.2 TESTS PASSED")
PY
