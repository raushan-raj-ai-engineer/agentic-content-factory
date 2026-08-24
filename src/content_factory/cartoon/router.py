from __future__ import annotations
import json, re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from content_factory.cartoon.channel_profiles import apply_channel_profile
from content_factory.cartoon.quality_reset_v17 import named_cast_from_topic
from content_factory.cartoon.capabilities import (
    infer_props,
    infer_visual_entities,
    resolve_action_families,
    resolve_topic_capabilities,
    resolve_topic_world_sequence,
)

@dataclass(frozen=True)
class CartoonRoute:
    primary: str
    audience: str
    tags: tuple[str, ...]
    locations: tuple[str, ...]
    pacing: str
    scores: dict[str, int]

def _root() -> Path:
    return Path(__file__).resolve().parents[3]

@lru_cache(maxsize=1)
def _payload() -> dict:
    return json.loads((_root()/"configs/cartoon_routes.json").read_text(encoding="utf-8"))

def _n(value: str) -> str:
    return re.sub(r"\s+"," ",(value or "").casefold()).strip()

def _contains_token(value: str, token: str) -> bool:
    token = _n(token)
    if not token:
        return False

    # Latin keywords must match complete words/phrases. This prevents
    # accidental routing such as `tota` inside `totally` or `work` inside
    # `homework`. Native-script keywords keep direct substring matching.
    if re.fullmatch(r"[a-z0-9 ]+", token):
        pattern = (
            r"(?<![a-z0-9])"
            + re.escape(token).replace(r"\ ", r"\s+")
            + r"(?![a-z0-9])"
        )
        return re.search(pattern, value) is not None

    return token in value


# V11.4: direct place mentions are stronger than broad world inference.
# These aliases map common English/Hindi/Bhojpuri/Magahi phrasing to the
# already-bundled background IDs. The parser preserves mention order and
# therefore works as a deterministic multi-location story arc without an
# extra LLM call.
_LOCATION_ALIASES: dict[str, tuple[str, ...]] = {
    "courtyard": ("courtyard", "backyard", "back yard", "patio", "aangan", "angan", "ghar ke aangan", "आंगन", "आँगन"),
    "living_room": ("living room", "drawing room", "बैठक", "बैठकखाना"),
    "tea_shop": ("tea shop", "chai shop", "chai dukan", "chai dukaan", "चाय दुकान", "चाय की दुकान"),
    "village_road": ("village road", "gaon ke road", "gaon ki sadak", "गाँव की सड़क", "गांव की सड़क"),
    "market": ("market", "bazaar", "bazar", "बाजार", "बाज़ार"),
    "classroom": ("classroom", "class room", "क्लासरूम", "कक्षा"),
    "office": ("office", "workplace", "ऑफिस"),
    "bus_stop": ("bus stop", "bus stand", "बस स्टॉप", "बस स्टैंड"),
    "bedroom": ("bedroom", "bed room", "सोने का कमरा"),
    "rooftop": ("rooftop", "roof top", "terrace", "छत"),
    "outdoor_kitchen": ("outdoor kitchen", "bahar ka kitchen", "बाहर की रसोई"),
    "mango_tree": ("mango tree", "aam ke ped", "आम का पेड़", "आम के पेड़"),
    "village_lane": ("village lane", "gaon ke gali", "gaon ki gali", "gali", "गली"),
    "school_yard": ("school yard", "school ground", "school playground", "स्कूल ग्राउंड", "स्कूल मैदान"),
    "playground": ("playground", "play ground", "खेल का मैदान"),
    "forest_path": ("forest path", "jungle path", "जंगल का रास्ता", "जंगल रास्ता"),
    "festival_ground": ("festival ground", "mela ground", "मेला मैदान"),
    "hospital": ("hospital", "clinic", "अस्पताल", "क्लिनिक"),
    "airport": ("airport", "airport terminal", "boarding gate", "एयरपोर्ट"),
    "train_station": ("train station", "railway station", "platform", "metro station", "subway station", "रेलवे स्टेशन", "प्लेटफॉर्म"),
    "restaurant": ("restaurant", "food court", "diner", "cafe", "cafeteria", "रेस्टोरेंट"),
    "kitchen": ("kitchen", "rasoi", "रसोई"),
    "farm": ("farm", "khet", "खेत"),
    "beach": ("beach", "seaside", "समुद्र किनारा", "बीच"),
    "space_station": ("space station", "spaceship", "spacecraft", "स्पेस स्टेशन", "अंतरिक्ष यान"),
    "laboratory": ("laboratory", "science lab", "research lab", "लैब"),
    "castle": ("castle", "fort", "किला"),
    "sports_field": ("sports field", "cricket ground", "football ground", "खेल मैदान"),
    "park": ("park", "garden", "पार्क", "बगीचा"),
    "city_street": ("city street", "downtown street", "neighborhood street", "suburban street", "main street", "शहर की सड़क"),
    "shop": ("shop", "store", "convenience store", "grocery store", "supermarket", "mall", "shopping center", "dukan", "dukaan", "दुकान"),
    "police_station": ("police station", "पुलिस स्टेशन"),
}

_ACTION_STORY_TOKENS = (
    "chase", "run after", "running after", "bhaag", "bhag", "daud", "daur",
    "pakad", "pakde", "peecha", "pichha", "पीछा", "भाग", "दौड़", "पकड़",
)

_SPECIALIZED_CAST = {
    "teacher", "doctor", "police", "astronaut", "robot", "alien",
    "dinosaur", "chef", "athlete", "worker", "wizard", "dog", "cat",
}

def resolve_explicit_location_sequence(topic: str) -> list[str]:
    value = _n(topic)
    hits: list[tuple[int, int, int, str]] = []
    for location_id, aliases in _LOCATION_ALIASES.items():
        for alias in aliases:
            alias_n = _n(alias)
            if not _contains_token(value, alias_n):
                continue
            pos = value.find(alias_n)
            if pos >= 0:
                hits.append((pos, pos + len(alias_n), -len(alias_n), location_id))

    # Prefer the longest phrase when aliases overlap. Example: `chai dukan`
    # must map to tea_shop only, not tea_shop + generic shop from `dukan`.
    hits.sort(key=lambda item: (item[0], item[2], item[3]))
    selected: list[tuple[int, int, str]] = []
    for start, end, _, location_id in hits:
        if any(start < chosen_end and end > chosen_start for chosen_start, chosen_end, _ in selected):
            continue
        selected.append((start, end, location_id))

    selected.sort(key=lambda item: item[0])
    result: list[str] = []
    for _, _, location_id in selected:
        if location_id not in result:
            result.append(location_id)
    return result

def is_chase_story(topic: str) -> bool:
    actions = resolve_action_families(topic)
    if any(action in {"chase", "run"} for action in actions):
        return True
    value = _n(topic)
    return any(_contains_token(value, token) for token in _ACTION_STORY_TOKENS)

def is_action_story(topic: str) -> bool:
    actions = resolve_action_families(topic)
    physical_actions = {
        "chase", "run", "walk", "enter", "exit", "jump", "fall",
        "grab", "give", "carry", "search", "hide", "magic",
        "celebrate", "dance", "open", "eat", "use_device", "point",
    }
    if any(action in physical_actions for action in actions):
        return True
    return is_chase_story(topic)

def _action_safe_cast(topic: str, capability_cast: list[str]) -> list[str]:
    """Avoid letting one incidental world inject a teacher/doctor/etc.

    Named roles remain authoritative. Only *implicit* world-role defaults are
    filtered for multi-location action stories.
    """
    explicit_entities = [str(x) for x in infer_visual_entities(topic)]
    value = _n(topic)
    named_core = [
        item for item in ("guddu", "bittu", "chacha", "mai", "babuji")
        if _contains_token(value, item)
    ]
    result: list[str] = []
    for item in [*explicit_entities, *named_core, "guddu", "bittu", *capability_cast, "chacha", "guest_child", "guest_adult"]:
        item = str(item)
        if item in _SPECIALIZED_CAST and item not in explicit_entities:
            continue
        if item not in result:
            result.append(item)
    return result[:5]

def route_topic(topic: str) -> CartoonRoute:
    value=_n(topic); rows=_payload()["routes"]; scores={}
    for row in rows:
        score=0
        for token in row.get("keywords",[]):
            token=_n(str(token))
            if _contains_token(value, token):
                score += 4 if " " in token else 2
        scores[row["id"]]=score
    if any(_contains_token(value, x) for x in ("bandar","बंदर","monkey")):
        scores["animal_comedy"] += 8; scores["kids_comedy"] += 2
    if any(_contains_token(value, x) for x in ("litti","लिट्टी","thekua","चोखा")):
        scores["food_comedy"] += 7; scores["village_comedy"] += 3
    if any(_contains_token(value, x) for x in ("magahi","मगही","bihari","bihar")):
        scores["village_comedy"] += 4
    if any(_contains_token(value, x) for x in ("magic","jadui","जादुई","invisible","गायब")):
        scores["magic_fantasy"] += 6
    if any(_contains_token(value, x) for x in ("school","स्कूल","homework","होमवर्क")):
        scores["school_comedy"] += 6
    if any(_contains_token(value, x) for x in ("goat","bakra","bakri","बकरा","बकरी")):
        scores["animal_comedy"] += 8
    if is_chase_story(topic):
        scores["adventure_chase"] += 10

    candidates=[r for r in rows if r["id"]!="general_comedy"]
    primary=max(candidates,key=lambda r:scores[r["id"]])
    if scores[primary["id"]] <= 0:
        primary=next(r for r in rows if r["id"]=="general_comedy")

    ranked=sorted(
        [(rid,s) for rid,s in scores.items() if rid!=primary["id"] and s>0],
        key=lambda x:(-x[1],x[0])
    )
    tags=list(primary.get("tags",[]))
    for rid,_ in ranked[:4]:
        row=next(r for r in rows if r["id"]==rid)
        for tag in row.get("tags",[]):
            if tag not in tags: tags.append(tag)
    return CartoonRoute(
        primary=primary["id"], audience=primary.get("audience","all"),
        tags=tuple(tags), locations=tuple(primary.get("locations",[])),
        pacing=primary.get("pacing","balanced"), scores=scores
    )

def _litti_pack(language_code: str) -> dict:
    scene_lines={
      "1":["माई, लिट्टी के खुशबू से पेट अभीए बाजा बजा रहल हई!","धीरज रखऽ, गरम निकलतई त जीभ मत जरा लिहऽ.","ए बिट्टू, उ पेड़ पर बंदरवा लिट्टी के देख रहल हई!"],
      "2":["देखऽ, बंदरवा धीरे-धीरे नीचे उतर रहल हई.","उ देखे दे, थारी पर हाथ रखलक त पकड़ लेब.","तोहर भरोसा देख के बंदरवा भी हँस रहल हई!"],
      "3":["अरे एss! हमर लिट्टी के थारी!","पकड़ऽ रे! बंदरवा पूरा थारी लेके भाग गेल!","ए बंदरवा, कम से कम चोखा त छोड़ जा!"],
      "4":["बिट्टू, दहिना से घेरऽ! ऊ गली तरफ भाग रहल हई!","हम घेरत हई, तू पहिले अपना चप्पल संभालऽ!","ई बंदर त हमनी से तेज निकसल रे!"],
      "5":["हटऽ, ई काम हमार हई; बंदर पकड़ना हम जानऽ हई!","चाचा, धीरे! नीचे कीचड़ हई!","अई मइया! पहिले हमरा निकालऽ, बंदर बाद में पकड़िहऽ!"],
      "6":["एक काम करऽ, थोड़ा चटनी रख दे; खुदे नीचे आ जाई.","वाह रे वैज्ञानिक! बंदर लिट्टी छोड़ के चटनी चाटे आई?","अरे! चटनीयो उठा लेलक—ई त तोहरा से दू कदम आगे हई!"],
      "7":["अरे बाप रे! लिट्टी हमर माथा पर गिरल!","पहिले लिट्टी बचावऽ, बाद में इज्जत खोजिहऽ!","ई बंदरवा चोरी कइके ऊपर से मजाक भी उड़ा रहल हई!"],
      "8":["रुकऽ... ई खुद ना खा रहल, अपना छोट बच्चा के खिला रहल हई.","तब्बे इतना जल्दी भागल रहे.","मतलब चोर कम, बच्चा खातिर जुगाड़ू बाप जादा हई!"],
      "9":["ठीक हई, बच्चा खातिर थोड़ा लिट्टी दे देतानी.","बस एक बात—हमरा हिस्सा बचल हई न?","अरेss! आखिरी लिट्टीयो लेके फिर भाग गेल!"],
    }
    if language_code not in {"magahi","hindi","bhojpuri","hinglish"}:
        scene_lines={}
    return {
      "key":"litti_chor_bandar",
      "goal":"लिट्टी बचाना और शरारती बंदर के पीछे मजेदार दौड़",
      "premise":"माई आँगन में गरम लिट्टी बना रहल हई। एक शरारती बंदर थारी उठाके भाग जाला। गुड्डू-बिट्टू पीछा करऽ हथिन, चाचा हीरो बने में फँस जा हथिन। बाद में पता चलऽ हई कि बंदर अपना बच्चा के खिला रहल रहे; अंत में ऊ आखिरी लिट्टीयो झपट ले जाला।",
      "preferred_cast":["guddu","bittu","mai","chacha","bandar"],
      "visual_by_scene":{str(i):["bandar"] for i in range(1,10)},
      "visual_actions":{
        "1":"cook_litti",
        "2":"monkey_sneak",
        "3":"steal_tray",
        "4":"chase",
        "5":"chacha_slip",
        "6":"bait_trap",
        "7":"food_chaos",
        "8":"baby_reveal",
        "9":"final_snatch"
      },
      "props_by_scene":{
        "1":["litti_tray","steam"],
        "2":["litti_tray"],
        "3":["litti_tray","motion_lines"],
        "4":["motion_lines"],
        "5":["dust_cloud"],
        "6":["chutney_bowl"],
        "7":["single_litti","motion_lines"],
        "8":["baby_monkey"],
        "9":["single_litti","motion_lines"]
      },
      "locations":["outdoor_kitchen","mango_tree","courtyard","village_lane","mango_tree","courtyard","mango_tree","mango_tree","courtyard"],
      "scene_directions":[
        ["माई लिट्टी बनावऽ हई; गुड्डू-बिट्टू इंतजार में; बंदर पेड़ से देख रहल हई.","पहिले 5 सेकंड में food + animal hook."],
        ["बंदर नीचे आवऽ हई और लिट्टी पर नजर गड़ावऽ हई.","Funny suspicion, short lines."],
        ["बंदर पूरा थारी झपट के भाग जाला.","Clear theft + chase start."],
        ["गुड्डू-बिट्टू गली में पीछा करऽ हथिन.","Fast physical chase."],
        ["चाचा expert बनऽ हथिन लेकिन खुद फिसल/फँस जा हथिन.","Big visual failure."],
        ["बिट्टू bait/chutney trap लगावऽ हई; बंदर trap उल्टा कर देला.","Second plan fails differently."],
        ["लिट्टी/थारी के बीच छोट chaos.","Fast cuts + reaction."],
        ["पता चलऽ हई बंदर अपना छोट बच्चा के खिला रहल हई.","Cute motive reveal."],
        ["माई थोड़ा लिट्टी दे दे हई; बंदर आखिरी लिट्टी झपट ले जाला.","Final callback punchline."]
      ],
      "scene_lines":scene_lines,
      "sfx_by_scene":{"2":["monkey_chatter"],"3":["thali_clang","whoosh"],"4":["footsteps","monkey_chatter"],"5":["boing","impact"],"7":["thali_clang","boing"],"8":["monkey_chatter"],"9":["whoosh","comic_sting"]},
    }


def _world_locations(topic: str, capability: dict[str, object]) -> list[str]:
    explicit = resolve_explicit_location_sequence(topic)
    if len(explicit) >= 2:
        # Directly named places are the story arc. Do not collapse them to the
        # strongest single capability world (e.g. school -> classroom).
        return explicit

    mapping = {
        "home": "living_room", "school": "classroom", "hospital": "hospital",
        "office": "office", "airport": "airport", "railway": "train_station",
        "restaurant": "restaurant", "farm": "farm", "beach": "beach",
        "city": "city_street", "police": "police_station", "sports": "sports_field",
        "science": "laboratory", "space": "space_station", "fantasy": "castle",
        "animal": "park", "dinosaur": "forest_path", "park": "park",
        "stage": "festival_ground",
    }
    worlds = resolve_topic_world_sequence(topic)
    ordered = [mapping[w] for w in worlds if w in mapping]

    # V11.2: multiple explicitly-mentioned worlds remain in narrative order.
    # For a single world, expose its related background choices instead of
    # collapsing every scene to one plate. This is capability-driven, not
    # topic-pack-specific, so future worlds inherit the same behavior.
    if len(ordered) > 1:
        return list(dict.fromkeys(ordered))[:4]
    if len(ordered) == 1:
        related = [str(x) for x in capability.get("backgrounds", [])]
        seed = explicit[0] if explicit else ordered[0]
        related = list(dict.fromkeys([seed, ordered[0], *related]))
        return related[:3]
    return list(dict.fromkeys(str(x) for x in capability.get("backgrounds", [])))[:3]


def _resolve_story_profile_base(*,topic:str,language_code:str)->dict[str,object]:
    route=route_topic(topic); value=_n(topic)
    if any(_contains_token(value, x) for x in ("litti","लिट्टी")) and any(_contains_token(value, x) for x in ("bandar","बंदर","monkey")):
        p=_litti_pack(language_code)
        p.update({"route":route.primary,"audience":"kids","tags":list(dict.fromkeys(list(route.tags)+["food","village","kids","chase","wholesome"])),"pacing":"fast_visual"})
        return p
    if any(_contains_token(value, x) for x in ("career","career choice","करियर")):
        local=language_code in {"hindi","magahi","bhojpuri","hinglish"}
        if local:
            goal = "गेम डिजाइनर"
            safe_path = "सरकारी या इंजीनियरिंग जैसी सुरक्षित नौकरी"
            project = "गुड्डू का खुद बनाया छोटा मोबाइल गेम"
            comparison = "शर्मा जी का इंजीनियर बेटा"
            premise = (
                "गुड्डू गेम डिजाइनर बनना चाहता है, लेकिन घर वाले सरकारी या "
                "इंजीनियरिंग जैसी सुरक्षित नौकरी चाहते हैं। शर्मा जी का "
                "इंजीनियर बेटा बार-बार तुलना में आता है। गुड्डू अपना बनाया छोटा "
                "मोबाइल गेम दिखाकर अपनी बात साबित करने की कोशिश करता है।"
            )
        else:
            goal = "game designer"
            safe_path = "a secure government or engineering-style job"
            project = "a small mobile game Guddu built himself"
            comparison = "Sharma ji's engineer son"
            premise = (
                "Guddu wants to become a game designer while the family prefers "
                "a safer conventional job and keeps comparing him with Sharma "
                "ji's engineer son. He tries to prove the choice with a small "
                "mobile game he built himself."
            )
        return {
          "key":"game_designer",
          "goal":goal,
          "safe_path":safe_path,
          "project":project,
          "comparison":comparison,
          "premise":premise,
          "route":route.primary,"audience":route.audience,"tags":list(route.tags),"pacing":route.pacing,
          "preferred_cast":["guddu","bittu","mai","babuji","chacha"],"locations":list(route.locations),
          "visual_by_scene":{},"scene_lines":{}
        }
    capability = resolve_topic_capabilities(topic)
    explicit_locations = resolve_explicit_location_sequence(topic)
    locations = _world_locations(topic, capability) or list(route.locations)
    topic_actions = resolve_action_families(topic)
    action_story = is_action_story(topic)
    primary_action = topic_actions[0] if topic_actions else ("chase" if action_story else "dialogue")
    raw_cast = [str(item) for item in capability.get("cast", [])]
    named_cast = named_cast_from_topic(topic)
    if action_story and len(explicit_locations) >= 2:
        preferred_cast = _action_safe_cast(topic, raw_cast)
    else:
        preferred_cast = raw_cast or ["guest_adult","guddu","bittu"]
    if named_cast:
        # V17: explicit recurring names in the user's premise always outrank
        # generic world-role defaults such as guest_adult.
        preferred_cast = list(dict.fromkeys(named_cast + preferred_cast))
        # If the topic explicitly names 2+ known recurring characters, do not
        # let a generic placeholder occupy the lead slot.
        if len(named_cast) >= 2:
            preferred_cast = [c for c in preferred_cast if c != "guest_adult"]
    topic_props = infer_props(topic)
    props_by_scene = {
        str(scene_id): topic_props[:6]
        for scene_id in range(1, 16)
        if topic_props
    }

    # Action scenes should not visually collapse to only the two speaking
    # characters. Extra cast members become non-verbal visual participants,
    # giving chase/search scenes crowd energy without extra dialogue/LLM calls.
    visual_by_scene: dict[str, list[str]] = {}
    if action_story:
        extras = [item for item in preferred_cast if item in {"guddu","bittu","chacha","guest_child","guest_adult"}]
        for scene_id in range(1, 16):
            visual_by_scene[str(scene_id)] = extras[:4]

    value = _n(topic)
    theft_like = any(_contains_token(value, token) for token in (
        "steal", "stole", "snatch", "chor", "chori", "leke bhaag", "leke bhag", "चोर", "चोरी", "झपट"
    ))
    opening_action = "grab" if action_story and theft_like else primary_action
    selfie_like = any(_contains_token(value, token) for token in ("selfie", "photo", "picture", "सेल्फी", "फोटो"))
    ending_action = "use_device" if selfie_like and "phone" in topic_props else "reaction"

    return {
      "key":f"route_{route.primary}","goal":topic.strip(),
      "premise":(
          f"Follow this exact user premise without changing its profession, "
          f"place, important object, or core action: {topic.strip()}."
      ),
      "route":route.primary,"audience":route.audience,"tags":list(route.tags),"pacing":route.pacing,
      "preferred_cast":preferred_cast[:5],"locations":locations,
      "forced_location_arc":explicit_locations if len(explicit_locations) >= 2 else [],
      "explicit_locations":explicit_locations,
      "action_story":action_story,
      "visual_by_scene":visual_by_scene,"scene_lines":{},
      "props_by_scene":props_by_scene,
      "capability_world":capability.get("world","neutral"),
      "topic_actions":topic_actions,
      "topic_props":topic_props,
      "primary_action":primary_action,
      "opening_action":opening_action,
      "ending_action":ending_action
    }


def resolve_story_profile(*, topic: str, language_code: str) -> dict[str, object]:
    """V14 channel-aware wrapper around the proven universal router."""
    base = _resolve_story_profile_base(topic=topic, language_code=language_code)
    return apply_channel_profile(base, topic=topic, language_code=language_code)
