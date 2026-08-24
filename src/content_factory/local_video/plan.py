from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import re


@dataclass
class Shot:
    scene_id: int
    shot_id: int
    character_id: str
    text: str
    emotion: str
    setup: str
    visual_action: str
    location_id: str
    source_image: Path

    @property
    def motion_prompt(self) -> str:
        action = self.visual_action.replace("_", " ") if self.visual_action else "natural household action"
        emotion = self.emotion or "natural"
        return (
            f"Family-friendly Indian cartoon scene in {self.location_id}. "
            f"{self.setup} The speaking character {self.character_id} performs {action}. "
            f"Expression is {emotion}. Natural hand, arm, head and body movement; visible object interaction; "
            "the listener reacts naturally. Preserve character identity, clothing and background. "
            "No text, no captions, no morphing, no extra fingers, no duplicate people."
        )


def load_plan(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("scenes"), list) or not data["scenes"]:
        raise ValueError("episode plan contains no scenes")
    return data


def image_for_scene(scene_id: int, image_dir: Path) -> Path:
    candidates = [
        image_dir / f"scene_{scene_id:02d}.png",
        image_dir / f"scene_{scene_id}.png",
        image_dir / f"scene_{scene_id:02d}.jpg",
        image_dir / f"scene_{scene_id}.jpg",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(f"No keyframe image for scene {scene_id} in {image_dir}")


def shots_from_plan(plan: dict, image_dir: Path, max_scenes: int | None = None, max_shots_per_scene: int | None = None) -> list[Shot]:
    shots: list[Shot] = []
    scenes = plan["scenes"][:max_scenes] if max_scenes else plan["scenes"]
    for scene in scenes:
        sid = int(scene["id"])
        image = image_for_scene(sid, image_dir)
        dialogue = scene.get("dialogue") or []
        if max_shots_per_scene:
            dialogue = dialogue[:max_shots_per_scene]
        for idx, turn in enumerate(dialogue, 1):
            text = re.sub(r"\s+", " ", str(turn.get("text", "")).strip())
            if not text:
                continue
            shots.append(Shot(
                scene_id=sid,
                shot_id=idx,
                character_id=str(turn.get("character_id", "default")),
                text=text,
                emotion=str(turn.get("emotion", "natural")),
                setup=str(scene.get("setup", "")),
                visual_action=str(scene.get("visual_action", "natural_action")),
                location_id=str(scene.get("location_id", "home")),
                source_image=image,
            ))
    return shots
