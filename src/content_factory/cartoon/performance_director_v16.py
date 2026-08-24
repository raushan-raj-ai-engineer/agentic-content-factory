from __future__ import annotations

from collections import Counter
from typing import Iterable

CROWD_LOCATIONS = {
    "school_yard", "classroom", "festival_ground", "playground",
    "auditorium", "stage", "assembly_ground", "sports_field",
}
CROWD_WORDS = (
    "speech", "assembly", "audience", "crowd", "stage", "sammelan", "kavi",
    "function", "annual day", "occasion", "principal", "students", "school event",
    "bhashan", "sabha", "manch", "समारोह", "सभा", "भाषण", "मंच", "कवि",
)
DIRECT_WORDS = ("camera", "viewers", "audience at home", "dosto", "दोस्तों")


def _scene_text(scene) -> str:
    pieces = [
        str(getattr(scene, "setup", "") or ""),
        str(getattr(scene, "visual_action", "") or ""),
        str(getattr(scene, "blocking_mode", "") or ""),
    ]
    for line in getattr(scene, "dialogue", []) or []:
        pieces.append(str(getattr(line, "text", "") or ""))
    return " ".join(pieces).casefold()


def interaction_mode(scene, characters: list[str], action: str) -> str:
    text = _scene_text(scene)
    location = str(getattr(scene, "location_id", "") or "").casefold()
    if action in {"run", "walk", "chase", "enter", "exit", "grab", "fall", "jump"}:
        return "action"
    if any(word in text for word in DIRECT_WORDS) and len(characters) <= 2:
        return "direct_address"
    crowd_hint = location in CROWD_LOCATIONS and len(characters) >= 4
    crowd_hint = crowd_hint or any(word in text for word in CROWD_WORDS)
    if crowd_hint:
        return "crowd_speech"
    if len(characters) == 2:
        return "paired_dialogue"
    if len(characters) >= 3:
        return "group_dialogue"
    return "direct_address"


def focal_speaker(timeline: list[dict[str, object]], characters: Iterable[str]) -> str | None:
    valid = set(characters)
    durations: Counter[str] = Counter()
    counts: Counter[str] = Counter()
    for item in timeline:
        cid = str(item.get("character_id", ""))
        if cid not in valid:
            continue
        start = float(item.get("start", 0.0) or 0.0)
        end = float(item.get("voice_end", item.get("end", start)) or start)
        durations[cid] += max(0.0, end - start)
        counts[cid] += 1
    if not durations:
        return next(iter(valid), None)
    return max(durations, key=lambda cid: (durations[cid], counts[cid]))


def line_addressee(
    timeline: list[dict[str, object]],
    line_index: int,
    characters: list[str],
    mode: str,
    focal: str | None = None,
) -> str | None:
    if not (0 <= line_index < len(timeline)):
        return None
    speaker = str(timeline[line_index].get("character_id", ""))
    if mode == "direct_address":
        return "camera"
    if mode == "crowd_speech":
        if focal and speaker == focal:
            # If the next line is a real interruption, the speaker's final beat
            # can naturally aim toward that interrupter; otherwise address group.
            for j in range(line_index + 1, min(len(timeline), line_index + 3)):
                other = str(timeline[j].get("character_id", ""))
                if other and other != speaker:
                    return other
            return "audience"
        return focal or "audience"

    # Conversation: next speaker is the most natural target; otherwise previous.
    for j in range(line_index + 1, len(timeline)):
        other = str(timeline[j].get("character_id", ""))
        if other and other != speaker and other in characters:
            return other
    for j in range(line_index - 1, -1, -1):
        other = str(timeline[j].get("character_id", ""))
        if other and other != speaker and other in characters:
            return other
    for other in characters:
        if other != speaker:
            return other
    return None


def gaze_direction(
    actor: str,
    target: str | None,
    positions: dict[str, tuple[int, int]],
) -> str:
    if not target or target == "camera":
        return "front"
    max_x = max((pos[0] for pos in positions.values()), default=960)
    center_x = 640 if max_x <= 1280 else 960
    ax = positions.get(actor, (center_x, 0))[0]
    if target == "audience":
        # A crowd speaker scans slightly toward the side opposite their stage
        # placement instead of staring into the lens.
        return "right" if ax < center_x else "left"
    if target not in positions:
        return "front"
    tx = positions[target][0]
    if tx > ax + 12:
        return "right"
    if tx < ax - 12:
        return "left"
    return "front"


def gaze_for_line(
    timeline: list[dict[str, object]],
    line_index: int,
    actor: str,
    characters: list[str],
    positions: dict[str, tuple[int, int]],
    mode: str,
    focal: str | None,
) -> str:
    target = line_addressee(timeline, line_index, characters, mode, focal)
    return gaze_direction(actor, target, positions)


def listener_gaze(
    speaker: str,
    listener: str,
    positions: dict[str, tuple[int, int]],
) -> str:
    return gaze_direction(listener, speaker, positions)


def crowd_full_rigs(
    timeline: list[dict[str, object]],
    characters: list[str],
    available: Iterable[str],
    max_full: int = 1,
) -> list[str]:
    """Return the tiny set of fully articulated crowd actors.

    Crowd scenes deliberately keep one focal performer fully articulated. Other
    participants remain lightweight until a future dedicated reaction shot.
    This is both more natural staging and far cheaper than N articulated rigs.
    """
    avail = [cid for cid in characters if cid in set(available)]
    if not avail or max_full <= 0:
        return []
    focal = focal_speaker(timeline, avail)
    return [focal] if focal else avail[:1]


def lightweight_positions(characters: list[str], focal: str | None) -> dict[str, tuple[int, int]]:
    """720p stage composition: focal actor center, audience/reactions at edges."""
    positions: dict[str, tuple[int, int]] = {}
    if focal:
        positions[focal] = (500, 155)
    others = [c for c in characters if c != focal][:4]
    slots = [(45, 330), (255, 360), (840, 360), (1040, 330)]
    for cid, slot in zip(others, slots):
        positions[cid] = slot
    return positions
