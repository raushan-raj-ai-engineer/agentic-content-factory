from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class CartoonCharacter:
    id: str
    display_name: str
    role: str
    age_group: str
    personality: tuple[str, ...]
    voice_role: str
    default_outfit: str
    expressions: tuple[str, ...]
    poses: tuple[str, ...]


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def character_registry() -> dict[str, CartoonCharacter]:
    path = (
        _project_root()
        / "configs"
        / "cartoon_characters.json"
    )

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    result = {}

    for item in payload["characters"]:
        character = CartoonCharacter(
            id=str(item["id"]),
            display_name=str(item["display_name"]),
            role=str(item["role"]),
            age_group=str(item["age_group"]),
            personality=tuple(
                str(value)
                for value in item["personality"]
            ),
            voice_role=str(item["voice_role"]),
            default_outfit=str(item["default_outfit"]),
            expressions=tuple(
                str(value)
                for value in item["expressions"]
            ),
            poses=tuple(
                str(value)
                for value in item["poses"]
            ),
        )

        result[
            character.id
        ] = character

    return result


@lru_cache(maxsize=1)
def background_ids() -> tuple[str, ...]:
    path = (
        _project_root()
        / "configs"
        / "cartoon_backgrounds.json"
    )

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    return tuple(
        str(item["id"])
        for item in payload["backgrounds"]
    )


def default_cast(
    limit: int = 4,
) -> list[str]:
    preferred = [
        "guddu",
        "bittu",
        "chacha",
        "mai",
        "babuji",
    ]

    available = character_registry()

    return [
        item
        for item in preferred
        if item in available
    ][:max(2, min(limit, 5))]
