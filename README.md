# Study engine v1.1.0 — beginner-first explain → flow video

v1.1 is the teaching-architecture correction after reviewing the real `final_video(10).mp4`. The previous engine could animate correctly while still feeling disconnected: the same agent/tool figures repeated, topic-level objects leaked into unrelated narration windows, and one composition could remain on screen for ~25–30 seconds.

v1.1 gives every substantive study chapter a deterministic mini-lesson: **WHAT IT MEANS → HOW IT FLOWS → EXAMPLE/IMPLEMENTATION → VERIFY/RECAP**. Visual labels are grounded primarily in the current narration, study scenes are shorter, and non-technical study subjects keep their real domain instead of being forced into software visuals.

Start with [v1.1 beginner-first notes](docs/STUDY_ENGINE_V110.md). Previous release notes remain in `docs/`.

## Key defaults

```dotenv
STUDY_ACTIVE_CHECKS=false
STUDY_CAMERA_STYLE=auto
STUDY_MOTION_DENSITY=auto
STUDY_ENVIRONMENT=auto
STUDY_BEGINNER_FIRST=true
STUDY_SCENE_MIN_WORDS=34
STUDY_SCENE_MAX_WORDS=48
CONTENT_FACTORY_VOICE_MAX_TEMPO=1.12
CONTENT_FACTORY_SCRIPT_TIMEOUTS_BEFORE_FAILOVER=2
STUDY_STORYBOARD_BATCH_SIZE=3
STUDY_STORYBOARD_LOCAL_BATCH_SIZE=1
STUDY_MAX_DETERMINISTIC_SCENE_RATIO=0.25
STUDY_MIN_MEDIAN_OCCUPANCY=0.070
```

The engine intentionally stops before voice/render if the script or storyboard cannot meet the teaching-quality gates after bounded repair.
