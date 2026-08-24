from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from content_factory.cartoon.models import CartoonEpisodePlan, CartoonScene


_ACTION_MOTION = {
    "run": "action_track",
    "walk": "action_track",
    "chase": "action_track",
    "enter": "directional_drift",
    "exit": "directional_drift",
    "jump": "action_track",
    "fall": "action_track",
    "grab": "focus_drift",
    "give": "focus_drift",
    "carry": "directional_drift",
    "search": "explore_drift",
    "hide": "explore_drift",
    "magic": "focus_drift",
    "reveal": "focus_drift",
    "use_device": "focus_drift",
    "celebrate": "focus_drift",
    "dance": "action_track",
    "eat": "gentle_drift",
    "point": "focus_drift",
    "reaction": "breathing_hold",
}

_VARIANTS = (
    "establishing",
    "wide_left",
    "wide_right",
    "medium_left",
    "medium_right",
    "center_detail",
)


def _motion_for(scene: "CartoonScene", *, location_changed: bool) -> str:
    if location_changed:
        return "establishing_drift"

    action = str(getattr(scene, "visual_action", "auto") or "auto").casefold()
    if action in _ACTION_MOTION:
        return _ACTION_MOTION[action]

    beat = str(getattr(scene, "beat", "") or "").casefold()
    if beat in {"reaction"}:
        return "breathing_hold"
    if beat in {"punchline", "callback"}:
        return "focus_drift"
    if beat in {"transition", "escalation"}:
        return "directional_drift"
    return "gentle_drift"


def apply_scene_dynamics(plan: "CartoonEpisodePlan") -> dict[str, object]:
    """Assign deterministic, topic-agnostic environment continuity metadata.

    This deliberately does not inspect a fixed story/topic pack. It only uses
    the already-planned scene location, beat and visual action. The same logic
    therefore applies to home, school, office, airport, fantasy, animal, space,
    or a new future capability world.
    """
    previous_location: str | None = None
    continuity_index = 0
    local_index = 0
    location_changes = 0
    motions: list[str] = []
    variants: list[str] = []

    for scene in plan.scenes:
        location = str(scene.location_id)
        location_changed = previous_location is None or location != previous_location

        if location_changed:
            continuity_index += 1
            local_index = 0
            if previous_location is not None:
                location_changes += 1
        else:
            local_index += 1

        scene.continuity_group = f"{continuity_index}:{location}"
        scene.location_changed = bool(location_changed)

        if location_changed:
            variant = "establishing"
        else:
            # Rotate through clearly different virtual camera zones while the
            # physical location stays continuous. This changes the pixels the
            # viewer sees, not just metadata, and remains topic-agnostic.
            variant = _VARIANTS[1 + ((local_index - 1) % (len(_VARIANTS) - 1))]

        motion = _motion_for(scene, location_changed=location_changed)

        scene.environment_variant = variant
        scene.environment_motion = motion
        variants.append(variant)
        motions.append(motion)
        previous_location = location

    location_counts = Counter(str(scene.location_id) for scene in plan.scenes)
    longest_static_location_run = 0
    run = 0
    previous_location = None
    for scene in plan.scenes:
        location = str(scene.location_id)
        if location == previous_location:
            run += 1
        else:
            run = 1
            previous_location = location
        longest_static_location_run = max(longest_static_location_run, run)

    return {
        "version": "11.3",
        "topic_agnostic": True,
        "extra_llm_calls": 0,
        "scene_count": len(plan.scenes),
        "location_changes": location_changes,
        "distinct_locations": len(location_counts),
        "location_counts": dict(location_counts),
        "environment_motions": dict(Counter(motions)),
        "environment_variants": dict(Counter(variants)),
        "longest_location_run": longest_static_location_run,
    }
