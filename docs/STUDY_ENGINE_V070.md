# Study engine v0.7.0 — review, improvements and setup

## What the review found
The supplied v0.6.6 already included Kokoro/Piper voice routing, finite-DSL Manim
scenes, topic-specific semantic repair, loudness QC and reference-art generation.
Those are retained. They are not newly introduced by this release.

Four concrete problems were addressed:
- Text-character positions approximated speech timing. Optional faster-whisper
  now runs on final pace-processed scene WAVs. Cue tokens match its word times;
  missing cues are explicitly estimated, never called measured alignment.
- Language metadata overwrote the study audience prefix, losing study pacing.
- Animated quick checks introduced waits while speech continued. The extra
  question wait is removed; answers require at least three elapsed seconds.
  A short scene may have no in-video answer reveal; the companion always has it.
- Loudness processing used a single dynamic pass. It now measures the same
  clarity chain before supplying measured values to a second normalization pass.
  FFmpeg may fall back to dynamic normalization where linear constraints fail.

## New learner experience
Script instructions require a concrete opening result/problem within 35 spoken
words, an honest skill payoff, predictions, misconception explanations and a
transfer exercise within the existing duration budget. This is an LLM instruction,
not a guarantee that every generated script has perfect pedagogy.

Semantic actions now consume an absolute audio-clock cue schedule. Render time
is bounded by scene duration. Existing code/array/browser/architecture/science
renderers remain scene-specific; no stock-footage or generic zoom fallback added.

Every completed study video also gets `video/lesson.html` and `lesson.json`.
Open lesson.html beside final_video.mp4: chapters, playback speed, chapter replay,
prediction choices, answer reveal and optional pauses at chapter changes work
locally without an account or CDN. The MP4 itself is not clickable. Choices are
self-check prompts, not automatically graded assessments.

## Mac setup (fresh folder recommended)
```bash
cd ~/Downloads/agentic-content-factory
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[voice,channel,alignment,dev]'
# If Manim native dependencies are missing on macOS:
# brew install ffmpeg cairo pango pkg-config
bash scripts/setup_kokoro_voice.sh
# Only create .env if you do not already have your own:
[ -f .env ] || cp .env.example .env
```
Keep existing API keys and model preferences. Add these to .env:
```dotenv
CONTENT_FACTORY_STUDY_VOICE_BACKEND=kokoro
STUDY_WORD_TIMING=auto
STUDY_WHISPER_MODEL=base
STUDY_AUDIO_MASTERING=1
```
`auto` attempts local ASR, then explicitly falls back if unavailable. `required`
stops on ASR failure/poor script coverage. `off` uses estimates and skips ASR.
The code default is off for backwards compatibility; the new .env.example uses
`auto`. First ASR use downloads a model; subsequent cached use is local. Use a
local model-directory path in STUDY_WHISPER_MODEL for a pre-provisioned machine.
CPU int8 and one cached ASR model limit memory overhead. An 8 GB Mac still needs
headroom for the LLM and renderer; avoid concurrent heavyweight diffusion jobs.

```bash
bash scripts/preview_voice.sh
bash run_topic.sh --topic "Python binary search: predict the midpoint, trace an example, and test edge cases"
```
Audition voices before a long lesson. A subjective “premium” voice is not
something this patch can guarantee. Kokoro quality, accent and pronunciation
vary with language/text. Existing Piper and macOS paths are retained.

## Diagnostics and limitations
- `audio/segment_N.timing.json`: exact WAV duration, ASR source, coverage, words.
- `audio/voice_manifest.json`: timing source and exact seconds for each segment.
- Segment `.alignment.json`: planned cue timestamps and measured-cue ratio.
  It is a schedule report, not proof of frame-perfect rendered synchronization.
- ASR is transcription-based timing, not forced alignment. Technical names,
  code and multilingual narration can be misrecognized. Coverage under 75%
  rejects ASR timing; unmatched individual cues fall back to estimates.
- Dense overlapping cues can still run late because animations take time.
  Review an actual clip before producing a long lesson.
- No paid service or external asset API was added. Existing selected LLM/image
  providers may still cost money; configure existing local providers to avoid that.

## Free resources checked on 2026-09-27
- Kokoro ONNX: https://github.com/thewh1teagle/kokoro-onnx — MIT inference;
  Kokoro weights Apache-2.0: https://huggingface.co/hexgrad/Kokoro-82M
- faster-whisper: https://github.com/SYSTRAN/faster-whisper — local CPU int8,
  word timestamps. Optional install extra; weights are not bundled.
- Piper voice terms vary by voice MODEL_CARD:
  https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/VOICES.md
- Existing Manim/Pillow/FFmpeg pipeline and original asset collection retained.
  No new stock images, music or third-party voice weights redistributed.

## Verification
See VALIDATION_V070.md for the actual checks performed. Full narrated Manim
render and real-model voice/ASR quality must be checked on the production machine.
