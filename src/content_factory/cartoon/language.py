from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


ALIASES = {
    "en": "english",
    "english": "english",
    "hi": "hindi",
    "hindi": "hindi",
    "हिंदी": "hindi",
    "hinglish": "hinglish",
    "hi-en": "hinglish",
    "magahi": "magahi",
    "मगही": "magahi",
    "bhojpuri": "bhojpuri",
    "भोजपुरी": "bhojpuri",
}


@dataclass(frozen=True)
class CartoonLanguagePack:
    code: str
    display_name: str
    script: str
    region_hint: str
    voice_locale_preferences: tuple[str, ...]
    native_writing_rule: str
    humor_guidance: tuple[str, ...]
    address_examples: tuple[str, ...]


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def available_languages() -> list[str]:
    folder = _project_root() / "configs" / "cartoon_languages"

    if not folder.is_dir():
        return []

    return sorted(
        path.stem
        for path in folder.glob("*.json")
    )


@lru_cache(maxsize=32)
def load_language_pack(
    language: str,
) -> CartoonLanguagePack:
    normalized = ALIASES.get(
        (language or "").strip().lower(),
        (language or "").strip().lower(),
    )

    if not normalized:
        raise ValueError(
            "Cartoon language is required."
        )

    path = (
        _project_root()
        / "configs"
        / "cartoon_languages"
        / f"{normalized}.json"
    )

    if not path.is_file():
        supported = ", ".join(
            available_languages()
        )

        raise ValueError(
            f"Unsupported cartoon language: {language!r}. "
            f"Available: {supported}"
        )

    data = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    return CartoonLanguagePack(
        code=str(data["code"]),
        display_name=str(data["display_name"]),
        script=str(data["script"]),
        region_hint=str(data["region_hint"]),
        voice_locale_preferences=tuple(
            str(item)
            for item in data.get(
                "voice_locale_preferences",
                []
            )
        ),
        native_writing_rule=str(
            data["native_writing_rule"]
        ),
        humor_guidance=tuple(
            str(item)
            for item in data.get(
                "humor_guidance",
                []
            )
        ),
        address_examples=tuple(
            str(item)
            for item in data.get(
                "address_examples",
                []
            )
        ),
    )


def infer_language_from_request(
    text: str,
    default: str = "hindi",
) -> str:
    value = (
        text
        or ""
    ).lower()

    patterns = (
        ("hinglish", r"\bhinglish\b"),
        ("bhojpuri", r"\bbhojpuri\b|भोजपुरी"),
        ("magahi", r"\bmagahi\b|मगही"),
        ("hindi", r"\bhindi\b|हिंदी|हिन्दी"),
        ("english", r"\benglish\b"),
    )

    for code, pattern in patterns:
        if re.search(
            pattern,
            value,
            flags=re.IGNORECASE,
        ):
            return code

    return ALIASES.get(
        default.lower(),
        default.lower(),
    )
