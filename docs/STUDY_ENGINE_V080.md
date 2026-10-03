# Study engine v0.8.0 — premium semantic motion

## Scope

This release keeps the existing research, strategy, script, fact-check, voice,
Manim, FFmpeg, lesson companion and human-gate architecture. The change is in
how an approved study scene is translated into motion: the finite storyboard DSL
now carries more explicit semantic actions and rendering direction instead of
forcing many different concepts through the same card/arrow animation.

## What changed

### Semantic storyboard actions

The storyboard action vocabulary now includes `split`, `merge`, `scan`, and
`stream` in addition to the existing finite safe action set. These describe the
meaning of the motion rather than arbitrary Python. Example mappings:

- document chunking -> `split`
- candidate/vector inspection -> `scan`
- retrieved evidence assembled into context -> `merge`
- generated answer appearing progressively -> `stream`

The renderer still consumes a validated finite schema. LLM-produced Python is
not executed.

### Visual direction metadata

A scene can now carry:

- `environment`: coherent scene world such as `document_space`, `data_space`,
  `code_lab`, `browser_space`, `science_lab`, or `security_boundary`
- `camera_style`: `static`, `guided`, `follow`, `focus`, or `cinematic`
- `transition_style`
- `motion_density`

The Visual Director chooses these by default. Optional `.env` overrides are:

```dotenv
STUDY_CAMERA_STYLE=auto
STUDY_MOTION_DENSITY=auto
STUDY_ENVIRONMENT=auto
```

`auto` is recommended because a single forced camera or environment for the
entire lesson reduces scene diversity.

### Scene environments and depth

The Manim scene now builds topic-appropriate procedural environments rather
than relying on one flat dark canvas. Background treatment remains intentionally
subtle so it does not compete with teaching content. Environments share the
existing channel aesthetic but vary their depth cues and supporting geometry.

### Guided camera

The study renderer now uses `MovingCameraScene`. Storyboard actions can reframe,
track a moving payload, focus a relevant object and gently return toward the
home framing. Camera movement is bounded and semantic; it is not a random zoom
layer.

### Live code presentation

The code scene no longer depends on a monolithic finished-code reveal. A stable
custom code panel allows `type_code` to reveal lines progressively and
`step_code` to dim unrelated lines while emphasizing the current line. This
keeps the code tied to the narration beat without allowing generated code to run.

### Topic-specific RAG repair upgraded

The deterministic RAG storyboard repair now uses semantic operations:

- chunking physically uses `split`
- similarity search performs `scan` before comparison/selection
- prompt/context assembly uses `merge`
- answer generation uses `stream`

These repairs also request scene-appropriate environments and camera behavior,
so the deterministic fallback benefits from the same motion system.

### Cache/render identity

The semantic visual policy is now `study-animation-v6-premium-semantic`, and
motion sidecars include `study-scene-engine-v6`. This gives downstream cache
and diagnostic logic a clear identity for the new scene engine.

## What deliberately did not change

- narration remains the timing authority
- existing word/cue timing and ASR fallback remain intact
- current voice-provider routing remains intact
- current two-pass audio mastering and loudness QC remain intact
- final study rendering remains 1920x1080/30 fps by default
- final H.264 path retains quality-based CRF rendering
- existing content/fact-check/human approval stages remain authoritative

The visual layer is not permitted to introduce new factual claims merely to
make a scene more interesting.

## Validation status in this package

The source compiles successfully. The non-YouTube automated suite passes:

```text
157 passed, 1 deselected
```

The focused study-engine semantic-motion tests pass as well. Full repository
collection in the packaging environment is blocked by the optional `yt_dlp`
dependency used by the YouTube research tests. That dependency is available via
the existing `research` extra and is unrelated to the scene-engine changes.

A final narrated Manim render was not produced in the packaging environment
because Manim is not installed there. Therefore this release does **not** claim
that visual premium quality is validated solely from unit tests. The production
machine should render and review an actual clip before a long run.

## Recommended validation on the production Mac

```bash
cd ~/Downloads/agentic-content-factory-study-v0.8.0-premium-motion
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[voice,channel,alignment,research,dev]'

# Keep the semantic director in control first.
export STUDY_CAMERA_STYLE=auto
export STUDY_MOTION_DENSITY=auto
export STUDY_ENVIRONMENT=auto

python -m pytest -q
bash run_topic.sh --topic "Retrieval-Augmented Generation explained with chunking, embeddings, retrieval, context construction and a Python example"
```

For the first generated lesson, inspect the hook plus chunking, vector search,
context assembly, answer generation and code scenes. Verify that the visual
operation itself expresses the narration: splitting should visibly split,
search should visibly scan/select, context should assemble, generation should
stream, and code should advance line by line.
