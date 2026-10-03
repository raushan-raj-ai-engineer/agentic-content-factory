# U.S. Viewer Scene Policy — v0.6.2

Study Mode defaults to a clear, active-learning presentation style for a U.S. educational YouTube audience. The policy remains configurable and subject-agnostic.

## Decisions implemented

1. **Concrete first 30 seconds** — the hook visualizes the learner problem and payoff immediately; it does not preview unrelated later concepts.
2. **Narration-locked semantic motion** — visual actions occur at verbatim narration cues. Code steps, protocol messages, math transformations, browser actions, security gates, graphs, and algorithms use subject-specific primitives rather than a repeated slide/flowchart template.
3. **One focal concept at a time** — normal scenes target 3–7 objects and reveal supporting elements progressively.
4. **Short U.S.-English labels** — concise labels, familiar left-to-right cause/effect flow when appropriate, and mobile-readable text.
5. **Sparse active checks** — about every four scenes, viewers get a short predict/recall/check prompt followed by the answer. This is cognitive interaction for ordinary YouTube video, not fake clickable UI.
6. **No decorative motion** — every beat must teach or emphasize something present in the current narration.

## Research basis

- YouTube Help, *Measure key moments for audience retention*: improve the opening 30 seconds and bring compelling moments earlier. https://support.google.com/youtube/answer/9314415
- Cambridge Handbook of Multimedia Learning, *Multimedia Learning with Instructional Video*: effective instructional video uses multimedia design principles and generative activities such as retrieval/self-explanation.
- Cambridge Handbook, *Signaling (Cueing) Principle*: cues help direct attention to essential material.
- Cambridge Handbook, *Coherence / temporal contiguity*: remove extraneous material and synchronize corresponding visuals with narration.
- Mayer, *Segmenting Principle*: complex narrated animation benefits from bite-sized segments.

## Configuration

```env
STUDY_VIEWER_MARKET=US
STUDY_ACTIVE_CHECK_EVERY=4
```

`STUDY_ACTIVE_CHECK_EVERY` is clamped to 3–6. Scene 1 never receives a quiz overlay.
