# SME Study Video Guide

This build is tuned for beginner-friendly Tech, AI, coding, automation, and software-testing education.

## 1. Generate an exact topic

Use `--topic` when you already know what you want to teach:

```bash
bash run_topic.sh --topic "RAG for beginners: explain the problem, retrieval, embeddings, vector databases, data flow, a small Python example, testing, limitations, and a practice question"
```

Other examples:

```bash
bash run_topic.sh --topic "AI Agents for beginners with a simple Python tool-calling example and testing strategy"
bash run_topic.sh --topic "Playwright fixtures in TypeScript for beginners with login fixture example and common mistakes"
bash run_topic.sh --topic "REST API testing with Python and pytest for beginners"
bash run_topic.sh --topic "Model Context Protocol MCP explained for SDETs"
```

The best prompt describes **how to teach**, not only the title. A strong pattern is:

> Explain `<TOPIC>` for beginners. Start with the problem it solves, plain-language theory, a simple analogy, important terms, step-by-step flow, a practical example/code, connect theory to implementation, show how to verify it, give concrete edge cases/limitations, then end with a practice question.

## 2. Let the system discover a safe topic

```bash
bash run_topic.sh --category technical
bash run_topic.sh --category ai
bash run_topic.sh --category software_testing
```

These three categories now use a **hard domain gate**. Sports, weather, celebrity, and unrelated mass-market trends cannot win a technical run. If current trend feeds contain too few safe topics, the pipeline adds category-safe curriculum topics and validates them against YouTube evidence.


## U.S. localization and narrator choice

Study Mode defaults to **English (United States)** for every technical, AI, software-testing, and clearly technical explicit-topic run. The script writer uses American English spelling/vocabulary and the voice director requests an `en_US` narrator.

The default local narrator profile is:

```text
locale: en-US
voice profile: us-male-warm
preferred local Piper voice: en_US-ryan-medium
```

This is an offline, warm U.S. male educational narrator profile. It is not the proprietary ElevenLabs Adam voice.

Normal Study Mode command (no voice options required):

```bash
bash run_topic.sh --category technical
```

Choose the U.S. female profile:

```bash
bash run_topic.sh --category technical --voice-profile us-female-clear
```

Choose an exact installed voice:

```bash
bash run_topic.sh --topic "RAG for beginners" --voice en_US-ryan-medium
bash run_topic.sh --topic "RAG for beginners" --voice Alex
```

Override localization when you intentionally want another market:

```bash
bash run_topic.sh --topic "RAG for beginners" --locale en-GB --voice-profile auto
```

List available local voices:

```bash
bash run_topic.sh --list-voices
```

Audition a voice before rendering a full video:

```bash
bash scripts/preview_voice.sh
bash scripts/preview_voice.sh --voice-profile us-female-clear
bash scripts/preview_voice.sh --voice Alex
```

`setup_channel.sh --cards` installs `en_US-ryan-medium` as the default U.S. study narrator and also attempts to install `en_US-lessac-medium` as an alternate U.S. female voice.

## 3. Deterministic DSA lessons

```bash
bash channel.sh dsa --topic binary-search --renderer cards
bash channel.sh dsa --topic two-sum --renderer cards
bash channel.sh dsa --topic move-zeroes --renderer cards
bash channel.sh dsa --topic palindrome --renderer cards
bash channel.sh dsa --topic character-frequency --renderer cards
```

Ollama is auto-detected by default for narration enhancement. The algorithm, trace, complexity, expected result, and edge-case truth remain deterministic.

## 4. Ollama model behavior

`configs/local.yaml` uses:

```yaml
llm:
  model: auto
```

The workflow reads `/api/tags` and selects an actually installed local model, preferring a small Qwen model and then Llama. If you configure a model that is missing, it falls back to an installed model and prints the choice instead of failing halfway through the workflow.

To require an exact model name instead:

```bash
export CONTENT_FACTORY_STRICT_LLM_MODEL=1
```

## 5. Teaching standard

For technical study videos the expected learning arc is:

**Problem → Beginner theory → Analogy/mental model → Step-by-step flow → Practical code/example → Theory-to-code mapping → Verification → Concrete edge cases/limitations → Complexity/tradeoffs → Practice**

The cards renderer keeps a continuous background between progressive reveal phases to avoid black-frame flicker.

## Study Mode vs current-news mode

`technical`, `ai`, and `software_testing` category runs use Study Mode. The discovery engine may still use current trend signals to find a useful topic, but once a topic is selected the lesson is taught from stable subject knowledge and authoritative fact packs. News dates, launches, adoption claims, quotes, and other time-sensitive statements are never required to fill the lesson and remain evidence-gated if used.

Typical Study Mode flow:

`topic discovery -> beginner strategy -> theory/mental model -> architecture/flow -> practical example/code -> verification/testing -> edge cases -> recap/practice -> production`

This is intentionally different from current-event mode:

`topic discovery -> current evidence -> evidence-bounded script -> strict current fact check -> production`

## Choose one LLM for a complete run

Study Mode supports Ollama, Gemini, OpenAI, Anthropic, and OpenAI-compatible APIs. Configure `.env` from `.env.example`.

The recommended default is:

```env
LLM_PROVIDER=auto
LLM_FALLBACK_ORDER=ollama,gemini,openai,anthropic,compatible
OLLAMA_MODEL=auto
```

`auto` is only a **startup selector**. After the CLI prints `[LLM LOCK]`, every text/reasoning agent uses that same provider and model until text generation is complete. The workflow never changes providers because one particular task is difficult or because a fact check failed.

To compare providers, run the same topic separately:

```bash
bash run_topic.sh --topic "RAG for complete beginners" \
  --llm-provider ollama --llm-model qwen3:4b-instruct

bash run_topic.sh --topic "RAG for complete beginners" \
  --llm-provider gemini --llm-model YOUR_GEMINI_MODEL
```

This creates clean model-level comparisons instead of mixing model behavior inside one video.


## Provider-agnostic structured output

Study agents do not contain Gemini/OpenAI/Claude-specific parsing logic. They call the common LLM interface. The selected provider adapter uses native schema output when supported and automatically falls back to schema-in-prompt JSON on the same locked model if that endpoint rejects native schema controls. This behavior applies uniformly to Strategy, Growth, Script, Packaging, Review, Fact Check, and production-planning agents.

## Adaptive lesson duration

Study Mode does not force every lesson into a standard length. The strategy estimates the time needed for the topic and audience, while the final narration length is reconciled from the actual script. A short concept may stay short; a deeper architecture or implementation lesson may run longer when the material genuinely requires it.

This is intentionally separate from scene pacing: total lesson length can grow while individual scenes and visuals remain paced for comprehension.

## Compact terminal result

Normal runs now end with a short summary containing status, locked LLM, script title/duration, fact-check status, final video path, thumbnail path, and the path to the complete JSON result.

To print the legacy full terminal output, add:

```bash
bash run_topic.sh --category technical --verbose-result
```

Full structured details are always retained in `workflow_result.json` even when the terminal stays compact.


## Cue-synchronized semantic study engine (v0.5.2)

The approved narration is now the timing source for animation. Each storyboard beat contains a short phrase copied from the scene narration; the renderer aligns that visual action to the phrase's position in speech. This prevents a scene from doing all meaningful animation in the first few seconds and then idling.

Study storyboards are also checked semantically, not only for motion. Analogy scenes must map real-world objects to technical objects, code scenes must show code progression, message/protocol scenes must move state, and validation/security scenes must visibly allow or reject concrete inputs. Generic `node/text/badge` overuse is penalized.

The local narrator is measured after synthesis. Neutral technical teaching targets roughly 144 WPM, with slower serious/code-heavy delivery and a slightly quicker hook. If Piper or a system voice renders too fast, FFmpeg `atempo` slows the WAV while preserving pitch. Look for:

```text
[VOICE PACE] target≈144wpm raw=... final=... adjusted=YES
[VOICE PACE SUMMARY] words=... duration=... overall≈...wpm
```

A Study Mode run also prints:

```text
[STUDY QUALITY] score=... generic_ratio=... specialized_pass=...
[STUDY RENDER QUALITY] repairs=.../... (...%); maximum=15%
```

If semantic quality is too weak or too many scenes need portable repair, the build fails rather than publishing a mechanically animated lesson.

## Animation is mandatory in Study Mode (v0.3.9)

A study video must not behave like a narrated slide deck. The visual generator writes an animation policy sidecar for every Study Mode scene. The assembler applies a profile based on visual type (`study_code`, `study_diagram`, `study_workflow`, `study_compare`, or `study_focus`) using output-frame-driven FFmpeg motion so animation cannot reset on every looped still frame.

After assembly, the workflow samples the final MP4 and uses `mpdecimate` to estimate how much visible motion survived. If motion retention is below `STUDY_ANIMATION_MIN_RETENTION` (default 35%), the run fails the Study Animation quality gate instead of reporting completion. Video duration remains adaptive to the topic and narration.

## Real element animation (v0.4.0)

Study Mode uses independent visual layers rather than moving one flattened slide. Technical scenes progressively reveal the title, teaching text, workflow boxes, arrows/connectors, and active focus highlights. Generic/non-technical study scenes receive a provider-agnostic layered fallback.

The assembler prints a line such as:

```text
[STUDY LAYERS] scene=scene_3.png beats=17 step≈1.42s; whole-frame zoom=OFF
```

If a Study Mode scene has no valid layered animation plan, assembly stops instead of applying zoom/pan.

## Semantic Manim Study Rendering (v0.4.1)

Study Mode is now scene-driven rather than template-driven. The semantic director evaluates the current topic and the current scene narration independently. The topic establishes domain context; the current scene decides the animation intent.

Examples:

- MCP universal-adapter explanation → many-to-one transform
- MCP host/client/server explanation → architecture network with moving messages
- MCP tools/resources/prompts → capability orbit
- MCP testing/failure scene → validation gate
- MCP security scene → trust-boundary animation
- RAG → document/retrieval/context pipeline
- Playwright → browser/locator/action/assertion animation
- API → request/response exchange or validation gate
- Binary Search → live array/pointer trace

The generated scene PNG remains scene/topic-specific reference art, but is never the primary animation surface. Whole-frame zoom is disabled for Study Mode.

## v0.4.2 scene-first routing

Study Mode no longer classifies the entire lesson from generic title words. The current scene narration/title/visual intent drives the semantic Manim archetype. The production domain is pinned to technical for Study Mode, preventing AI/software lessons from using career/public-photo visual routes.

On Manim failure, inspect `artifacts/<topic>/<run>/visuals/scene_N.manim-error.log`.


## Narration-driven storyboard engine (v0.5.0)

The animation decision is now made from the current scene narration rather than from a fixed topic template. A Study Animation Director creates 3-10 typed objects and 4-12 teaching beats per scene. Beats are distributed across actual audio duration. The renderer has distinct objects for code, arrays, browsers, protocol packets, servers/clients, tools/resources, databases/vector stores, validation gates, security boundaries and other teaching mechanisms.

Cross-scene repetition is tracked using a storyboard signature (layout + object kinds + action sequence). Adjacent complete duplicates are repaired before rendering. Labels are sanitized to reject scene titles and generic sentence fragments. If LLM planning fails, the deterministic fallback still emits storyboard data and never falls back to zoom/pan.


## Renderer resilience (v0.5.1)

Storyboard generation intentionally uses the shared schema-in-prompt structured path because the storyboard DSL is nested and vendor-native schema support differs by model generation. The output is still validated against the same Pydantic storyboard models.

For rendering, code and terminal text avoid hard-coded font-family names. A failed rich Manim scene is retried once with a portable semantic repair plan that keeps object-level animation and narration order. Study Mode never falls back to static-slide zoom/pan.


## Resilient storyboard recovery (v0.5.3)

A malformed structured-output batch no longer discards every scene or terminates a valid lesson. The director first retries each affected scene independently using the same locked provider/model. Specialized scenes are then contract-repaired (for example, security boundaries require allow/reject behavior and protocol scenes require visible state travel) and re-scored. Deterministic fallback is scoped to the individual scene only.


## v0.5.5 universal study presentation + bidirectional voice normalization

- Kokoro/Piper/macOS narration now normalizes in both directions: slow segments can be gently accelerated and fast segments slowed without pitch shift.
- Study audio caps only abnormally long (>0.90s) synthetic pauses while preserving ~0.45s breathing room, then reports overall WPM, active-speech WPM and silence ratio.
- Study Mode itself now forces educational pacing for every subject; Math/Science lessons no longer depend on technology keywords to receive study narration.
- Persistent `STUDY MODE` / template headers were removed. Scene titles are compact, contextual and fade after the first teaching beat.
- Storyboard objects scale responsively by scene complexity so 3-5 object scenes use substantially more of the 1080p canvas and remain readable on mobile.
- Software visuals no longer share one rounded-box grammar: host/client/server/tool/resource/prompt use distinct visual forms.
- Code panels are larger, limited to the most relevant lines, and retain narration-synchronized line stepping.
- Message/data beats now draw the route and physically move packets; security allow/reject beats visibly traverse the boundary; analogy transforms replace the real-world object with its technical counterpart.
- Added reusable Math/Data primitives (`equation`, `graph`, `chart`, `number_line`, `shape`, `quantity`, `vector`) and Science primitives (`atom`, `molecule`, `wave`, `experiment`).
- Deterministic fallback is subject-aware for Math and Science rather than forcing software client/server diagrams.
- Storyboard quality now tracks a meaningful state-change ratio in addition to generic-object and specialized-scene correctness.
- Renderer label: V11 `mobile-first-physical-semantic-study-animation`.

## v0.5.4 strategy-first duration + Kokoro study voice
- Study duration now follows the approved strategist estimate by default.
- `--duration-minutes N` overrides the strategy for one run; `STUDY_DURATION_MINUTES=N` provides a persistent user preference.
- Short study drafts are expanded at the chunk/section level instead of silently collapsing a 14-minute strategy into a 7-minute lesson.
- U.S. Study Mode can use local Kokoro ONNX narration. `auto` prefers Kokoro when installed, with `am_michael` as the default male narrator and `af_bella` as the clear female alternative. Piper/macOS remain fallbacks.
- Install the free local model once with `bash scripts/setup_kokoro_voice.sh`.


## v0.5.7 temporal narration lock and final audio mastering

Study Mode now treats each voice segment as a strict visual time window. Specialized visual grammars (security boundary, code execution, browser UI, Math primitives, Science primitives) are allowed only when the current narration actually contains those concepts. If an LLM storyboard jumps ahead, the scene is repaired to a current-narration-safe storyboard before rendering.

The final Study MP4 is mastered after concatenation. Defaults:

```env
STUDY_AUDIO_MASTERING=1
STUDY_AUDIO_TARGET_LUFS=-16.0
STUDY_AUDIO_TRUE_PEAK_DBTP=-1.5
STUDY_AUDIO_LUFS_TOLERANCE=1.2
```

A render cannot complete if final loudness falls outside the configured tolerance. Hooks are also constrained to be informative and source-grounded so scene 1 has a concrete problem/mechanism to visualize.


## v0.5.8 Study polish

- Mobile-first renderer geometry: larger objects/code, brighter secondary labels, and no near-empty scene starts.
- First-frame semantic priming uses only first-beat objects from the current narration window.
- Final MP4 visual QC measures empty-frame ratio, foreground occupancy, and foreground luminance; sparse/dim lessons fail instead of shipping.
- Analogy noun locking prevents invented substitutions (for example, a wall socket when narration says smartphone/camera).
- Whole-word subject-family detection prevents technical lessons from accidentally falling into Math/Science fallback grammars.
- Added native device/app/sensor study primitives for grounded technology analogies.
- Dialogue mastering adds gentle speech-presence EQ and light compression before the existing -16 LUFS / -1.5 dBTP normalization.
- V13 renderer label: mobile-readability-continuous-temporal-semantic-study-animation.

## v0.5.9 readability QC and self-repair

Final Study MP4 validation separates spatial occupancy from readable-edge contrast. Dark cards/panels no longer lower a foreground-luminance score simply because the theme is dark. If spatial composition passes but text/stroke edge contrast is low, one bounded post-render contrast repair is applied and the MP4 is re-measured. Empty/sparse composition still fails. Configure only when needed with `STUDY_MIN_EDGE_LUMA`, `STUDY_MIN_P10_EDGE_RATIO`, and `STUDY_VISUAL_CONTRAST_FILTER`.

Storyboard planning uses 5-scene batches by default; set `STUDY_STORYBOARD_BATCH_SIZE` from 3 to 6 to trade request count against structured-output size. The same provider/model stays locked for the full run.



## Hybrid cinematic ambient references

For selected opener/context scenes, Study Mode can generate a premium cinematic reference image using the local Premium Creative backend. The image is then used as low-opacity ambient art while the actual explanation is rendered with semantic Manim objects and animations.

- AI hero generation is OFF by default; set `CONTENT_FACTORY_STUDY_AI_HERO=1` only if you explicitly want one textless opener background
- Falls back automatically if the premium backend is unavailable
- Does not replace semantic teaching animation


## v0.6.1 precision-motion visual policy

Study scenes use deterministic, textless cinematic backdrops. Titles, labels, code, equations, diagrams, and instructional words are drawn by Manim so spelling is exact. AI image generation is not used for normal study scenes. Optional AI ambience is limited to the first scene and is disabled by default.

For faster rendering on typical Apple Silicon:

```bash
export CONTENT_FACTORY_STUDY_RENDER_PARALLEL=2
```

For maximum safety/clarity keep:

```bash
export CONTENT_FACTORY_STUDY_AI_HERO=0
```
