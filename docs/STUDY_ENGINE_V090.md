# Study engine v0.9.0 — teaching-directed video

## Why v0.9 exists

The actual v0.8 RAG render was technically healthy but not yet good educational video. A review of `final_video(8).mp4` showed four viewer-facing problems:

1. **The same visual grammar kept returning.** A gold `User Query` card and retriever-style nodes appeared across unrelated explanations.
2. **The relationship between objects was weak.** Moving payloads were often labelled `data`, so the viewer could see motion without knowing whether it represented a question, evidence, context, or an answer.
3. **The open-book mental model was not actually shown as an open-book experience.** It frequently fell back to technical boxes.
4. **Active-learning cards interrupted the lesson.** `PAUSE & PREDICT` overlays covered the teaching visual while narration continued.

v0.9 treats these as direction/architecture defects, not styling defects.

## New teaching contract

Every scene should answer three questions:

- **What is the one thing the learner needs to understand now?**
- **What should they literally watch happen?**
- **What visual output becomes the input to the next idea?**

The renderer should not choose a generic diagram just because the narration contains words such as `query`, `retrieval`, or `context`.

## RAG chapter direction

The common RAG learning sequence now has distinct visual grammar:

- **Hook:** query UI → model → private sources → cited answer panel.
- **Information gap:** model memory is visually separated from fresh/private information.
- **Definition:** retrieval, embedding, augmentation, and generation are shown as different physical operations.
- **Open-book analogy:** student + open book first; then the analogy maps into model + retrieved context.
- **Architecture:** ingestion uses document/chunks/vector store; retrieval uses semantic point-cloud search; generation uses a context window and source-linked answer.
- **Code:** each code scene advances to a different state instead of replaying the same four-line snippet.
- **Verification:** retrieval quality, evidence grounding, and failure cases use different visual systems.
- **Tradeoffs:** comparison/chart/document views are selected from the actual tradeoff being narrated.

## New semantic objects

The finite storyboard DSL now includes:

- `search_ui`
- `book`
- `point_cloud`
- `context_window`
- `answer_panel`

These are deterministic Manim objects, not generated Python and not diffusion-rendered teaching text.

## Payload meaning

Movement no longer defaults to a pill labelled `data`.

The renderer derives semantic payload labels such as:

- `question`
- `evidence`
- `vector`
- `context`
- `answer`
- `request`
- `result`

This makes arrows and movement understandable without forcing the learner to infer what is travelling.

## Interruptions / viewer questions

Normal YouTube study output is uninterrupted by default:

```dotenv
STUDY_ACTIVE_CHECKS=false
```

If you explicitly want course-style checks:

```dotenv
STUDY_ACTIVE_CHECKS=true
STUDY_ACTIVE_CHECK_EVERY=4
```

The Manim renderer also checks this setting at render time, so an old cached storyboard containing interaction prompts will not unexpectedly put a quiz over a normal YouTube render.

The offline `lesson.html` companion follows the same rule.

## Voice consistency

v0.9 keeps U.S. character inserts in the Kokoro family when Kokoro is available, instead of falling directly to a macOS system voice.

```dotenv
KOKORO_CHARACTER_VOICES=am_fenrir,am_puck,af_bella,af_nicole
```

Automatic time stretching is more conservative:

```dotenv
CONTENT_FACTORY_VOICE_MAX_TEMPO=1.12
CONTENT_FACTORY_VOICE_MIN_TEMPO=0.90
```

This intentionally prefers a slightly longer natural sentence over an aggressively accelerated one.

## Cache/version boundary

v0.9 uses:

- storyboard: `study-storyboard-v4-teaching-directed`
- scene engine: `study-scene-engine-v7`
- motion policy: `study-animation-v7-teaching-directed`
- portable Manim repair: `portable-semantic-v3`

This prevents old v0.8 visual caches from silently standing in for the new teaching-directed scene plans.

## Validation

In the build environment:

- focused v0.9 teaching-director tests: **PASS**
- non-YouTube regression suite: **162 passed, 1 deselected**
- Python compile check: **PASS**

The environment used to build the ZIP does not include Manim, so the final acceptance test remains an actual render on the creator machine. Do not judge v0.9 only by test results; review the produced MP4 for comprehension, relationship clarity, and scene continuity.

## Relationship-first direction

v0.9 also adds an explicit relationship-first directing rule: every visible object must participate in the teaching idea, moving payloads are named (`question`, `evidence`, `vector`, `context`, `answer`), and multi-scene processes carry forward only the minimum object needed to connect one result to the next. For the RAG architecture chapter, the generation scene now begins with the top retrieved match and the original question, visibly merges them into the context window, then hands that context to the model before the answer streams out.

The `What to Watch Next` ending is no longer forced into a generic RAG recap. Its visuals are allowed to follow the actual closing narration so the end screen does not introduce unrelated verification or pipeline elements.
