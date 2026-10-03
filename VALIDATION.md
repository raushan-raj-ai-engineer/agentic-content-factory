## v0.6.1 validation — 26 September 2026

- Study visual default route is deterministic and does not invoke the premium diffusion worker.
- Deterministic backdrops contain no rendered text; teaching text stays in Manim/Pango.
- Optional AI hero is opt-in and limited to scene 1.
- Study render concurrency defaults to 2, capped at 2.
- Targeted v0.6.1 tests: 7 passed.
- Broader non-live regression: 126 passed, 1 deselected.
- 33 deterministic AI-agent backdrops benchmarked at ~13 seconds total in this build environment before provider overhead; a 4-scene provider smoke completed in ~1.6 seconds.
- Full Python compile and shell syntax checks passed.
- Ruff/Mypy were not available in the build container and are not claimed here.

## v0.6.0 validation — 26 September 2026

- Added hybrid study opener path for technical/AI lessons using premium creative reference art.
- Added cinematic ambient reference styling in Manim via `reference_style=cinematic_ambient`.
- Backward compatible: if premium local model is unavailable, rendering falls back to deterministic technical visuals.

## v0.5.9 validation — 26 September 2026

- Focused Study/storyboard suite: **32 passed**.
- Broader suite excluding live/manual YouTube research: **119 passed, 1 deselected**.
- Legacy v0.5.7 MP4 under v0.5.9 QC: still **FAILS** for real spatial defects (`empty≈8%`, low p10/p25 occupancy) while its readable-edge luminance is correctly recognized as adequate.
- Dark-panel false-positive regression: legacy all-foreground p25 luminance ≈40.4, new readable-edge QC **PASS**.
- Contrast-only self-repair regression: **PASS after automatic repair**.
- Python compile: **PASS**.
- Shell syntax: **PASS**.
- Ruff/mypy were not available in the build container, so no pass claim is made for those tools in this build.

## v0.5.8 validation — 26 September 2026

- Study/duration focused regression suite: **51 passed**.
- Broader application suite excluding the environment-only YouTube import test: **115 passed, 1 deselected**.
- Python compile check: PASS.
- Build container does not have `yt_dlp`; the user's Mac environment does, so `tests/test_youtube_research.py` was excluded from the broad run rather than counted as a product failure.
- Reviewed v0.5.7 final MP4 visual QC: **FAIL** under v0.5.8 gates (empty≈8.0%, p25 occupancy≈0.017, foreground luma≈42.7).
- Real uploaded-video 60-second sample through v0.5.8 dialogue-clarity + final mastering: approximately **-16.0 LUFS / -1.5 dBTP**, QC PASS.
- Synthetic quiet MP4 loudness regression also passes.
- Ruff is not installed in this build container, so no Ruff pass is claimed here.
- Manim final E2E remains a target-Mac render validation; semantic renderer/planner regression tests pass.



## v0.5.8 Study polish

- Mobile-first renderer geometry: larger objects/code, brighter secondary labels, and no near-empty scene starts.
- First-frame semantic priming uses only first-beat objects from the current narration window.
- Final MP4 visual QC measures empty-frame ratio, foreground occupancy, and foreground luminance; sparse/dim lessons fail instead of shipping.
- Analogy noun locking prevents invented substitutions (for example, a wall socket when narration says smartphone/camera).
- Whole-word subject-family detection prevents technical lessons from accidentally falling into Math/Science fallback grammars.
- Added native device/app/sensor study primitives for grounded technology analogies.
- Dialogue mastering adds gentle speech-presence EQ and light compression before the existing -16 LUFS / -1.5 dBTP normalization.
- V13 renderer label: mobile-readability-continuous-temporal-semantic-study-animation.

## v1.2.1 phase-aware storyboard diversity gate

Beginner-first lessons intentionally repeat two pedagogical grammars: `EXPLAIN` uses the theory board and `FLOW` uses a process flow. The semantic quality gate now reports raw lesson-wide layout dominance for diagnostics but only hard-gates layout dominance across flexible phases (`hook`, `example`, `implementation`, `verify`, `recap`, `cta`). Adjacent semantic similarity and clone detection remain lesson-wide, so genuinely repeated scenes are still rejected.
