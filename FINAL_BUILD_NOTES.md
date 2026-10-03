# Agentic Content Factory — v0.6.2

## v0.6.2 U.S. active-learning scene clarity

- Study storyboards now default to `STUDY_VIEWER_MARKET=US` for concise American-English labels and familiar cause/effect presentation.
- Scene direction explicitly follows coherence, signaling, narration/visual temporal alignment, and active-retrieval principles instead of decorative motion.
- Roughly every four scenes, a short mobile-readable `CHECK` overlay asks the viewer to predict/recall from the scene and then reveals the answer. Frequency is configurable with `STUDY_ACTIVE_CHECK_EVERY` (3–6).
- Interactions are derived from semantic storyboard actions and never replace narration-driven animation.
- Scene 1 remains a concrete, fast hook and never receives a quiz overlay.
- The existing v0.6.1 deterministic textless backdrops + exact Manim teaching layer remain the default.

# Agentic Content Factory — v0.6.1

## v0.6.1 Precision Motion Study Engine

Study Mode no longer uses diffusion-generated teaching frames by default. Raw study PNGs are now fast deterministic textless cinematic backdrops; all readable English, code, equations, labels, and diagrams are rendered deterministically by Manim. This eliminates garbled AI text/prompt leakage and removes the multi-minute local image-generation bottleneck.

- `CONTENT_FACTORY_STUDY_AI_HERO=0` by default.
- Optional AI art is restricted to scene 1 only and its prompt forbids text, letters, numbers, code glyphs, signage, logos, and written UI.
- Deterministic scene-specific cyan/violet backdrops are generated with Pillow and contain no text.
- Manim remains the teaching surface for exact text, code, graphs, nodes, packets, state changes, and worked examples.
- Study Manim scenes render up to 2 at a time by default (`CONTENT_FACTORY_STUDY_RENDER_PARALLEL=2`).
- V16 renderer label: `precision-motion deterministic-study-visuals self-healing-readability-temporal-semantic-study-animation`.


## v0.6.0 Hybrid cinematic study openers

Study Mode now supports selective cinematic ambient reference art for opener/context/overview/recap scenes using the local Premium Creative backend (Z-Image-Turbo / MLX) while keeping the actual teaching animation deterministic in Manim. This gives technical lessons a more premium visual identity without sacrificing semantic teaching precision.

- New hybrid path for selected study scenes: premium creative reference art -> ambient semantic Manim animation overlay.
- The v0.6.0 heuristic AI-reference selection is superseded by the v0.6.1 deterministic Study policy.
- Storyboard manifests now carry `reference_style` so Manim can treat cinematic references differently from normal semantic references.
- Video banner advanced to V15.

# Agentic Content Factory — v0.5.9

## v0.5.9 Study readability resilience

v0.5.9 fixes the v0.5.8 false-block where dark panel fills were included in a 25th-percentile foreground-luminance score. Readability QC now separates composition occupancy from readable high-contrast edges (text, code strokes, borders, arrows). Empty/sparse composition remains a hard blocker. Contrast-only failures receive one bounded final-video FFmpeg repair and are re-measured before the workflow can fail.

Renderer defaults are also brighter for dark-theme study content: panel tones, muted text, divider strokes and secondary-object focus opacity were raised without changing the charcoal background. The final audio mastering and temporal/analogy locks from v0.5.8 remain unchanged.

Storyboard planning defaults to five scenes per locked-LLM batch (configurable with `STUDY_STORYBOARD_BATCH_SIZE`, clamped 3–6), reducing normal 30-scene planning calls while preserving the existing batch failure -> per-scene rescue -> deterministic fallback chain.

### Visual QC contract

- `empty_ratio <= 3%`
- `p10 occupancy >= 0.0075`
- `p25 occupancy >= 0.018`
- median readable-edge luminance `>= 50`
- p10 readable-edge coverage `>= 0.003`
- contrast-only failure -> automatic bounded repair -> re-measure
- sparse/empty failure -> still blocks

### Regression evidence

- A synthetic dark panel with legacy foreground-p25 luminance around 40 (the same range that blocked v0.5.8) now passes because its actual text/stroke edges are bright and readable.
- A deliberately dim but spatially valid frame triggers contrast repair and passes after repair.
- The reviewed v0.5.7 MP4 still fails for genuine empty/sparse composition (about 8% empty samples), proving the gate was corrected rather than disabled.
- Study/storyboard focused tests: 32 passed.
- Broader non-live application regression: 119 passed, 1 deselected.
- Python compile and shell syntax: PASS.

## Loudness + temporal alignment release

This release preserves the v0.5.6 Gemini quota-aware retry behavior and adds two production gates based on the reviewed Study MP4:

- final Study audio mastering: default -16 LUFS integrated, <= -1.5 dBTP true peak, with hard QC
- current-narration temporal lock: visual concepts cannot jump ahead of the spoken segment
- informative Study hook contract: concrete learner problem + mechanism/payoff; generic rhetorical hooks are rejected
- hook-only retention optimization can be accepted even when an oversized intro is rejected
- source-grounded hook fallback uses an already-approved first-section sentence rather than inventing a claim
- specialized storyboard repair blocks premature security/code/browser/Math/Science visuals
- all-subject fallback no longer treats the generic software word `function` as evidence that a technical scene is Math
- V12 renderer label: temporal-lock-loudness-mastered-semantic-study-animation

The final mastering step is configurable through `.env.example`.


## v0.5.8 Study polish

- Mobile-first renderer geometry: larger objects/code, brighter secondary labels, and no near-empty scene starts.
- First-frame semantic priming uses only first-beat objects from the current narration window.
- Final MP4 visual QC measures empty-frame ratio, foreground occupancy, and foreground luminance; sparse/dim lessons fail instead of shipping.
- Analogy noun locking prevents invented substitutions (for example, a wall socket when narration says smartphone/camera).
- Whole-word subject-family detection prevents technical lessons from accidentally falling into Math/Science fallback grammars.
- Added native device/app/sensor study primitives for grounded technology analogies.
- Dialogue mastering adds gentle speech-presence EQ and light compression before the existing -16 LUFS / -1.5 dBTP normalization.
- V13 renderer label: mobile-readability-continuous-temporal-semantic-study-animation.


## Deep-review closure

The reviewed v0.5.7 MP4 is now a negative regression fixture conceptually: v0.5.8's final visual QC rejects its measured 8% near-empty samples, low p25 foreground occupancy, and low foreground luminance. Renderer changes address those causes directly by priming the first semantic objects, enlarging mobile layouts, raising secondary-object opacity, and widening code views. Analogy nouns are narration-locked and subject families use word/phrase matching rather than substring heuristics.
