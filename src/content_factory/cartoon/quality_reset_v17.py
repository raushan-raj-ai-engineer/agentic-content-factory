from __future__ import annotations

import math
import os
import re
from pathlib import Path

from content_factory.cartoon.models import CartoonDialogueLine

INDIAN_CHANNEL = "hindi_mass"

_NAMED_ALIASES = (
    ("babuji", ("babuji", "babu ji", "बाबूजी", "बाबू जी")),
    ("guddu", ("guddu", "गुड्डू")),
    ("bittu", ("bittu", "बिट्टू")),
    ("mai", ("maa", "mai", "mummy", "मम्मी", "माँ", "मां", "माई")),
    ("chacha", ("chacha", "चाचा")),
    ("teacher", ("teacher", "masterji", "master ji", "टीचर", "मास्टरजी", "मास्टर जी")),
    ("doctor", ("doctor", "डॉक्टर")),
    ("police", ("police", "पुलिस")),
)


def _norm(value: str) -> str:
    return " ".join(str(value).casefold().replace("-", " ").split())


def named_cast_from_topic(topic: str) -> list[str]:
    text = _norm(topic)
    found: list[tuple[int, str]] = []
    for cid, aliases in _NAMED_ALIASES:
        positions = []
        for alias in aliases:
            a = _norm(alias)
            m = re.search(r"(?<!\w)" + re.escape(a) + r"(?!\w)", text, flags=re.UNICODE)
            if m:
                positions.append(m.start())
        if positions:
            found.append((min(positions), cid))
    found.sort()
    return [cid for _, cid in found]


def _words(text: str) -> list[str]:
    return re.findall(r"[\w\u0900-\u097f]+", str(text), flags=re.UNICODE)


def dialogue_word_count(scenes) -> int:
    return sum(len(_words(line.text)) for scene in scenes for line in scene.dialogue)


_HINDI_LINES = [
    "रुको, पहले ये समझो कि गड़बड़ शुरू कहाँ हुई, फिर अगला कदम उठाते हैं।",
    "एक मिनट, अभी जो हुआ है वो हमारी योजना में था ही नहीं।",
    "तुम लोग आसान बात को इतना घुमा देते हो कि मुश्किल खुद शर्माने लगे।",
    "ठीक है, अब कोई नया प्रयोग नहीं; पहले पिछली गलती का हिसाब करो।",
    "मुझे शुरुआत से शक था कि पाँच मिनट का काम पूरा कार्यक्रम बनने वाला है।",
    "अच्छा, अब हँसना बंद करो और बताओ अगली मुसीबत कौन संभालेगा।",
    "यही दिक्कत है, सबको shortcut चाहिए और नतीजा हमेशा full-size आता है।",
    "बस, अब समझ आया—गलती छोटी थी, confidence जरूरत से ज्यादा बड़ा था।",
    "पहले बात सीधी थी, अब हम समाधान से ज्यादा explanation दे रहे हैं।",
    "जो भी अगला idea देगा, पहले वही उसकी जिम्मेदारी भी लेगा।",
    "इतनी जल्दी मत करो, पिछली जल्दी का नतीजा अभी सामने खड़ा है।",
    "मैं सिर्फ इतना पूछ रहा हूँ कि योजना कहाँ खत्म हुई और तमाशा कहाँ शुरू हुआ।",
    "अब कोई बहाना नहीं, जो हुआ है उसे ठीक भी हम लोगों को ही करना है।",
    "देखो, समस्या कम है; उसे लेकर हमारा confidence ज्यादा खतरनाक है।",
    "अगर यही तरीका चलता रहा तो काम से पहले हमारी कहानी viral हो जाएगी।",
    "एक बात तय है, अगली बार शुरू करने से पहले instructions सच में पढ़ेंगे।",
    "अभी रुक जाओ, वरना छोटी सी बात का दूसरा भाग भी बन जाएगा।",
    "मुझे लग रहा है असली comedy काम में नहीं, हमारी planning में है।",
    "चलो, अब एक बार बिना shortcut के करके देखते हैं, शायद चमत्कार हो जाए।",
    "बस इतना याद रखना, अगली गलती पर कोई नहीं बोलेगा कि idea मेरा था।",
    "जो होना था हो गया; अब कम से कम ending इज्जत वाली कर लेते हैं।",
    "इतना confidence देखकर तो गलती भी सोच रही होगी कि दोष किसे दूँ।",
    "रुको, इस बार जवाब देने से पहले दो सेकंड सच में सोच लो।",
    "अच्छा, अब समझ में आया कि समस्या क्यों हर scene में बड़ी होती जा रही है।",
]

_MAGAHI_LINES = [
    "अरे रुकऽ, पहिले बुझऽ गड़बड़ शुरू कहाँ से भेल, फेर अगिला काम करिहऽ।",
    "हम त पहिले कहले रही, जल्दी के चक्कर में काम अउर बढ़ जइतै।",
    "एतना confidence कहाँ से आवऽ हउ, जब plan हर बेर उल्टा पड़ऽ हइ।",
    "पहिले ई झंझट ठीक करऽ, फेर नया experiment के नाम लऽ।",
    "पाँच मिनट के काम रहे, तू लोग पूरा कार्यक्रम बना देलऽ।",
    "अब हँसऽ मत, अगिला मुसीबत के जिम्मा के लेतै ई बतावऽ।",
    "shortcut खोजते-खोजते रास्ता ही लंबा कर देलऽ हउ।",
    "अब बुझायल—गलती छोट रहे, भरोसा बहुत बड़ा रहे।",
    "एक बेर बिना होशियारी दिखवले काम कर के देखऽ, शायद काम बन जाए।",
    "अगिला idea देवे वाला पहिले ओकर जिम्मेदारी भी लेतै।",
]


def _bank(language_code: str) -> list[str]:
    if str(language_code).casefold() in {"magahi", "bhojpuri"}:
        return _MAGAHI_LINES + _HINDI_LINES
    return _HINDI_LINES


def enforce_dialogue_budget(*, scenes, target_minutes: int, language_code: str, cast_ids: list[str]):
    """Repair severe under-length Hindi-channel scripts locally, with no extra LLM call.

    The normal prompt should already hit the budget. This guard only prevents a
    requested 2-minute episode from silently collapsing to a 20-second clip.
    """
    if os.getenv("CONTENT_FACTORY_CARTOON_CHANNEL", "auto").strip().lower() != INDIAN_CHANNEL:
        return scenes, {"enabled": False, "expanded_lines": 0, "before": dialogue_word_count(scenes), "after": dialogue_word_count(scenes)}
    before = dialogue_word_count(scenes)
    min_total = max(110, int(target_minutes) * 125)
    target_total = max(min_total, int(target_minutes) * 145)
    if before >= min_total:
        return scenes, {"enabled": True, "expanded_lines": 0, "before": before, "after": before, "min_words": min_total, "target_words": target_total}

    per_scene = max(34, math.ceil(min_total / max(1, len(scenes))))
    bank = _bank(language_code)
    used = 0
    expanded = 0
    for sidx, scene in enumerate(scenes):
        scene_words = sum(len(_words(line.text)) for line in scene.dialogue)
        speakers = [line.character_id for line in scene.dialogue if line.character_id in cast_ids]
        if not speakers:
            speakers = list(cast_ids[:2])
        while scene_words < per_scene and len(scene.dialogue) < 8 and used < len(bank):
            speaker = speakers[(len(scene.dialogue) + sidx) % max(1, len(speakers))]
            text = bank[used]
            used += 1
            scene.dialogue.append(CartoonDialogueLine(
                character_id=speaker,
                text=text,
                emotion="confused" if scene.beat in {"misdirection", "reaction"} else ("smirk" if scene.beat in {"punchline", "callback"} else "serious"),
                pose="thinking" if scene.beat in {"setup", "reaction"} else "pointing",
                pause_after_seconds=0.16,
            ))
            scene_words += len(_words(text))
            expanded += 1
        if dialogue_word_count(scenes) >= target_total:
            break
    after = dialogue_word_count(scenes)
    return scenes, {"enabled": True, "expanded_lines": expanded, "before": before, "after": after, "min_words": min_total, "target_words": target_total}


def natural_actor_alias(character_id: str) -> str | None:
    mapping = {
        "guddu": "guddu",
        "bittu": "bittu",
        "babuji": "babuji",
        "mai": "mai",
        "teacher": "teacher",
        "doctor": "doctor",
        "guest_child": "guest_child",
        "guest_adult": "dadaji",
        "dadaji": "dadaji",
        "chacha": "babuji",
    }
    return mapping.get(character_id)


def natural_actor_path(project_root: Path, character_id: str, direction: str = "front") -> Path:
    alias = natural_actor_alias(character_id)
    if not alias:
        return Path("/__missing_v17_actor__")
    d = direction if direction in {"front", "left", "right"} else "front"
    return Path(project_root) / "assets" / "cartoon_v17" / "actors" / alias / f"{d}.png"


def natural_actor_available(project_root: Path, character_id: str) -> bool:
    if os.getenv("CONTENT_FACTORY_CARTOON_CHANNEL", "auto").strip().lower() != INDIAN_CHANNEL:
        return False
    return natural_actor_path(project_root, character_id, "front").is_file()


def apply_hindi_mass_location_policy(topic: str, profile: dict[str, object]) -> dict[str, object]:
    """Keep implicit family/home comedy inside a coherent home world.

    Explicit user locations always win. This prevents generic capability
    expansion from sending a living-room family premise to an unrelated
    market/city street merely to create visual variety.
    """
    if os.getenv("CONTENT_FACTORY_CARTOON_CHANNEL", "auto").strip().lower() != INDIAN_CHANNEL:
        return profile
    explicit = profile.get("explicit_locations", [])
    forced = profile.get("forced_location_arc", [])
    if (isinstance(explicit, list) and explicit) or (isinstance(forced, list) and forced):
        return profile
    route = str(profile.get("route", "")).casefold()
    if route not in {"family_comedy", "route_family_comedy"}:
        return profile

    text = _norm(topic)
    home = ["living_room", "courtyard"]
    if any(k in text for k in ("kitchen", "rasoi", "रसोई", "खाना", "ghar ka kaam", "घर का काम")):
        home.append("outdoor_kitchen")
    elif any(k in text for k in ("roof", "rooftop", "छत")):
        home.append("rooftop")
    elif any(k in text for k in ("bedroom", "कमरा", "bed room")):
        home.append("bedroom")
    else:
        home.append("outdoor_kitchen")
    profile["locations"] = home
    profile["capability_world"] = "home"
    profile["v171_location_lock"] = True
    return profile
