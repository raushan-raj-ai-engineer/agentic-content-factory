# Study engine v1.1.0 — beginner-first explain → flow

## Why v1.1 exists

A review of the real `final_video(10).mp4` showed a structural teaching problem rather than a rendering crash. The narration could discuss one idea while the screen kept showing the same AI-agent/tool composition. Several sampled frames tens or hundreds of seconds apart were effectively the same composition. The viewer had to infer how the spoken explanation related to the figures.

The root causes were:

- study narration windows were often ~25–30 seconds, so one composition stayed visible too long;
- scene planning had no explicit pedagogical role, so the director inferred meaning from broad topic keywords;
- topic-level objects such as `AI Agent` were allowed to dominate current-narration objects;
- every study topic was previously forced toward the technical domain, even when the subject was science/history/etc.;
- script prompts asked for teaching depth but did not force each section to explain meaning before showing mechanism;
- the renderer represented `agent`, `model`, and `user` with similar circular geometry, increasing visual sameness.

## v1.1 teaching contract

Every substantive study chapter is emitted as a mini-lesson:

1. **EXPLAIN — WHAT IT MEANS**  
   One focal concept, plain-language relationship, no full process dump.
2. **FLOW — HOW IT WORKS**  
   A clear left-to-right cause → action → result diagram, revealed in narration order.
3. **EXAMPLE / IMPLEMENTATION**  
   Concrete scenario or code only after the mental model exists.
4. **VERIFY / RECAP**  
   Check the result, failure mode or final mental model without defaulting to security ALLOW/BLOCK visuals.

The first two phases are mandatory when a substantive section is long enough to support two narration windows.

## Important implementation changes

- `VisualScene` now carries `learning_phase`, `chapter_title`, and chapter scene position metadata.
- Study scenes default to shorter 34–48 word narration windows (configurable).
- Long one-scene sections are split at an existing sentence boundary so the first window explains and the second window shows flow.
- `StudyAnimationDirectorAgent` treats `learning_phase` as a hard contract.
- EXPLAIN scenes use a large focal concept with limited supporting objects.
- FLOW scenes use an explicit left-to-right mechanism with sequential semantic movement.
- Visible labels prefer nouns from the **current narration/chapter**, not only the overall topic.
- Mid-video quiz/rhetorical-question prompts are not forced by the script writer.
- Study domain classification is no longer unconditionally forced to technical.
- Agent, model and user now have visually distinct deterministic primitives.
- Manim logs expose the learning phase for every rendered scene.

## Defaults

```dotenv
STUDY_BEGINNER_FIRST=true
STUDY_SCENE_MIN_WORDS=34
STUDY_SCENE_MAX_WORDS=48
STUDY_ACTIVE_CHECKS=false
STUDY_CAMERA_STYLE=auto
STUDY_MOTION_DENSITY=auto
STUDY_ENVIRONMENT=auto
```

Keep `STUDY_BEGINNER_FIRST=true` for normal beginner educational YouTube videos.
