from __future__ import annotations
import json, os
from functools import lru_cache
from pathlib import Path

from content_factory.cartoon.indian_comedy_v15 import indian_comedy_prompt_block


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def _payload() -> dict:
    p=_root()/"configs/channel_profiles.json"
    return json.loads(p.read_text(encoding="utf-8"))


def resolve_channel_name(requested: str|None, language_code: str) -> str:
    value=(requested or "auto").strip().lower()
    if value not in {"", "auto"}:
        if value not in _payload()["channels"]:
            raise ValueError(f"Unknown channel profile: {value}")
        return value
    return str(_payload()["default_by_language"].get(language_code, "global_english" if language_code=="english" else "hindi_mass"))


def current_channel(language_code: str|None=None) -> str:
    env=os.getenv("CONTENT_FACTORY_CARTOON_CHANNEL", "auto")
    return resolve_channel_name(env, language_code or "english")


def channel_profile(language_code: str|None=None) -> dict:
    name=current_channel(language_code)
    out=dict(_payload()["channels"][name]); out["id"]=name
    return out


def channel_prompt_block(language_code: str) -> str:
    p=channel_profile(language_code)
    if p["id"]=="global_english":
        return (
            "GLOBAL ENGLISH CHANNEL: Write idiomatic, natural international English suitable for US/UK/EU viewers. "
            "Prefer universally relatable family, school, pet, work, travel and everyday-situation humor. "
            "Do not force Indian kinship terms, Sharma-ji style comparisons, government-job stereotypes or translated-English phrasing unless the user explicitly requests Indian context. "
            "Use short conversational punchlines, visual comedy and culturally neutral names/settings when the topic is neutral."
        )
    return (
        "HINDI MASS CHANNEL V15: Use naturally spoken Hindi/Hinglish/Magahi/Bhojpuri exactly as requested. "
        "Optimize for culturally rooted, relatable Indian humor across city, small-town and village audiences without forcing stereotypes.\n"
        + indian_comedy_prompt_block(language_code)
    )


def channel_character_name(character_id: str, fallback: str) -> str:
    if channel_profile()["id"]!="global_english":
        return fallback
    aliases={
        "guddu":"Alex", "bittu":"Leo", "guest_child":"Kid", "guest_adult":"Adult",
        "mai":"Mom", "babuji":"Dad", "chacha":"Uncle", "teacher":"Teacher",
        "doctor":"Doctor", "police":"Police Officer", "worker":"Worker", "chef":"Chef",
        "athlete":"Athlete", "astronaut":"Astronaut", "wizard":"Wizard"
    }
    return aliases.get(character_id, fallback)


def apply_channel_profile(profile: dict, *, topic: str, language_code: str) -> dict:
    p=channel_profile(language_code)
    out=dict(profile)
    out["channel"]=p["id"]
    out["audience_region"]=p.get("audience_region", "global")
    out["humor_style"]=p.get("humor_style", "relatable comedy")
    out["background_family"]=p.get("background_family", "natural")
    if p["id"]=="global_english":
        current=[str(x) for x in out.get("preferred_cast", [])]
        specialists=[x for x in current if x in {"teacher","doctor","police","astronaut","robot","alien","dinosaur","chef","athlete","worker","wizard","dog","cat"}]
        preferred=[]
        for x in specialists + list(p.get("preferred_cast", [])) + current:
            if x not in preferred: preferred.append(x)
        out["preferred_cast"]=preferred[:5]
        if not out.get("explicit_locations"):
            remap={"tea_shop":"restaurant","mango_tree":"park","outdoor_kitchen":"kitchen","temple":"park","festival_ground":"park","village_lane":"city_street","village_road":"city_street"}
            out["locations"]=[remap.get(str(x),str(x)) for x in out.get("locations", [])]
    return out
