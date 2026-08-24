from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceProfile:
    character_id: str
    label: str
    tempo: float
    bass_gain_db: float
    presence_gain_db: float
    target_lufs: float = -14.0


VOICE_PROFILES: dict[str, VoiceProfile] = {
    # Older authority: slower, warmer, less bright.
    "babuji": VoiceProfile("babuji", "deep_slow_authority", 0.92, 2.0, -1.0, -14.0),
    # Quick-witted younger voice: slightly faster and brighter.
    "guddu": VoiceProfile("guddu", "light_quick", 1.04, -0.5, 1.5, -14.0),
    # Confidently-wrong energy: fastest / brightest male profile.
    "bittu": VoiceProfile("bittu", "energetic_fast", 1.10, -1.0, 2.2, -14.0),
    # Practical deadpan: steady, slightly warm female profile.
    "mai": VoiceProfile("mai", "firm_deadpan", 0.97, 1.0, 0.5, -14.0),
    "default": VoiceProfile("default", "neutral", 1.0, 0.0, 0.0, -14.0),
}


def profile_for(character_id: str) -> VoiceProfile:
    return VOICE_PROFILES.get(character_id, VOICE_PROFILES["default"])
