# v0.7.0 validation

Performed in the supplied-source workspace on 2026-09-27:

- `python -m pytest -q --disable-warnings --maxfail=1 --ignore=tests/manual`
  **156 passed, 1 deselected** (12.74 seconds).
- Six new regression cases cover exact WAV duration, repeated spoken cue
  matching, bounded fallback cues, required/auto timing failure, low ASR coverage
  and companion chapter timing/HTML script escaping.
- `python -m compileall -q src`: passed.
- Ruff: new timing module and new tests pass configured rules. Companion module
  passes with E501 excluded for the embedded HTML/CSS/JS template. This is not a
  claim that inherited repository-wide Ruff debt was fixed.
- Real FFmpeg smoke test: 8-second synthetic tone + video processed by the new
  two-pass mastering code. Input -21.8 LUFS; output -16.0 LUFS; true peak -13.3
  dBTP; built-in audio QC passed. This proves processing works, not speech quality.

Not validated here:
- Real Kokoro/Piper voice synthesis and subjective listening quality.
- Real faster-whisper model inference; ASR boundary/failure behavior was mocked.
- Full Manim narrated lesson rendering or frame-by-frame cue synchronization.
- Browser UI automation: installed Playwright lacked a Chromium executable.
  Companion serialization/security and timing were unit-tested; visual/UI behavior
  still needs a browser smoke check on the production machine.

No full learner-engagement study was performed. The hook and pedagogy rules are
prompt improvements; the companion enables user-controlled practice.
