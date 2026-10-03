# SME Video Upgrade

This build applies the review feedback from the generated study-video preview.

Implemented:

- study narration pacing around 145–160 WPM by teaching stage
- short scene-end breathing pauses
- 1920×1080 DSA/card/Manim output
- progressive three-stage card reveals instead of one static image
- Manim pointer/callout/comparison animations
- explicit LOW/MID/HIGH and READ/WRITE visual state
- eliminated-state rendering for algorithm traces
- stronger question-first hooks
- mental-model-first lesson structure
- code → reasoning → verification teaching identity
- complexity explained from mechanism
- edge-case and practice scenes
- deterministic SME pedagogy quality gate
- pacing and pedagogy reports in each DSA run
- SME-aware Ollama narration rewrite constraints
- general Tech/AI script prompts updated for expert teaching structure
- technical script reviewer checks for jargon, missing reasoning, verification, and overly dense narration
- technical/education production scene planning aligned to ~150 WPM
- technical voice profile slowed while non-study/news delivery remains unchanged
- 1080p technical visual renderer using Mental Model + How It Flows layout
- browser demo capture upgraded to 1080p and study-paced narration

Validation performed in the review environment:

- channel tests: 7 passed
- selected non-network core tests: 22 passed, 1 deselected
- all five DSA templates pass the deterministic SME pedagogy review
- 1080p progressive card renderer was rendered and probed successfully
- full repository test collection could not run because the review environment does not have optional `yt_dlp` and `onnxruntime` dependencies installed

Final publication review is still required. The pedagogy gate validates teaching structure; it is not a factual oracle.
