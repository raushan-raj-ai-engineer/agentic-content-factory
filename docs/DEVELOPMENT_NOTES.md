# Agentic Content Factory — Development Notes

_Last updated: 2026-08-24_

## 1. Project Goal

`agentic-content-factory` is a local-first automated content pipeline intended to:

1. discover real trending topics,
2. enrich the selected topic with current evidence,
3. build an evidence-grounded content strategy,
4. generate and review a YouTube script,
5. fact-check the script,
6. create a production plan,
7. generate voice and visuals,
8. assemble a final video,
9. create packaging/growth assets,
10. run a monetization-safety review.

Primary local machine: Apple Silicon M2 with 8 GB unified memory.

---

## 2. Current Pipeline

```text
Google Trends / Google News / YouTube / Hacker News
                         |
                         v
                Research Planner
                         |
                         v
                 Trend Research
                         |
                         v
               Evidence Enrichment
                         |
                         v
               Content Strategist
                         |
                         v
               Strategy Grounding
                         |
                         v
                Growth Strategy
                         |
                         v
                Approval Gate
                         |
                         v
                 Script Writer
                         |
                         v
             Authenticity / Retention
                         |
                         v
               Packaging Optimizer
                         |
                         v
                Script Reviewer
                         |
                         v
                 Fact Checker
                         |
                         v
                Fact Check Gate
                         |
                         v
               Script Approval
                         |
                         v
              Content Production
                         |
                         v
             Production Approval
                         |
                         v
                Voice Generation
                         |
                         v
               Visual Generation
                         |
                         v
                 Video Assembly
                         |
                         v
             Monetization Safety
```

---

## 3. Current Local Stack

### LLM

- Local model: `llama3.2`
- Runtime: Ollama
- Used for strategy, script writing, review, planning, fact-check reasoning, packaging and growth logic.
- The LLM does **not** directly render the final MP4.

### Voice

- Piper + macOS voices are available.
- Existing voice profiles should remain unchanged unless there is a genuine voice-quality issue.

### Visual / Video

Runtime currently reports:

```text
[VISUAL] Premium Visual Engine V4 enabled.
[VIDEO] V4 quality output: 1080p30 / H.264 CRF17 / BT.709 / motion-aware.
```

The existing V4 path creates/prepares scene visuals and assembles video. It is not the same as a full text-to-video foundation model generating every frame.

### Assembly

- FFmpeg
- 1080p30
- H.264
- CRF17
- BT.709

---

## 4. Fact Checker Fixes

### Original Bug

A previous run showed:

```text
[FACT] Found 0 issue(s). Auto-repairing script once.
[FACT] BLOCKED after repair: 5 issue(s) remain.
```

Correct behavior:

```text
0 material issues -> PASS -> NO REPAIR
real issues > 0 -> repair once -> re-check -> PASS/BLOCK
```

### V20.2

V20.2 added a zero-issue guard and monetization-diversity preparation.

Goals:

- never repair an already-clean script,
- preserve the existing real-issue repair path,
- add scene-treatment diversity,
- avoid treating one renderer backend as automatically repetitive,
- generate monetization/disclosure review artifacts.

### Zero-Issue State Assignment Bug

A later run failed with:

```text
RuntimeError: Fact checker reported 0 issues without a FactCheckResult
```

Root cause:

- first fact-check result existed locally,
- it contained zero issues,
- but `state.fact_check` had not been assigned before the zero-issue PASS branch.

### V20.4

V20.4 was created as a surgical state-assignment fix:

```text
first.issues == []
        |
        v
state.fact_check = first
        |
        v
approved = True
        |
        v
repair = SKIPPED
        |
        v
PASS
```

Status: the latest workflow stopped earlier in Script Writer, so this path still needs end-to-end revalidation in a successful run.

---

## 5. Monetization Safety Changes

A previous monetization gate reported:

```text
[MONETIZATION] Risk: HIGH
[MONETIZATION] Upload ready: NO
[MONETIZATION] HIGH: Nearly the entire video uses one visual treatment, creating a template/slideshow feel.
```

### V20.2 Diversity Preflight

Production-plan treatment rotation included:

- opening context,
- evidence board,
- timeline,
- comparison split,
- headline context,
- key points,
- what to watch,
- closing synthesis.

Goal: materially different scene composition, not merely different prompts with the same slideshow layout.

### Duration-Aware Narration Floor

A fixed internal 450-word minimum was too strict for short legitimate videos.

Observed example:

```text
319 words
duration = 2 minutes
```

V20.4 changed the internal narration-length heuristic to be duration-aware rather than using one fixed minimum.

This does **not** bypass the monetization gate. Other originality and scene-variation checks remain active.

---

## 6. Script Writer Findings

### Successful Example

```text
825 words
duration = 6 minutes
Script Writer = 49.6s
```

### Short Script Example

```text
319 words
duration = 2 minutes
```

The system correctly reconciled duration to actual narration length instead of pretending 319 words equals seven minutes.

### 600-Second Timeout

Latest observed failure:

```text
[START] Script Writer Agent
[PERF] Script Writer Agent: 600.1s (failed)

RuntimeError:
Ollama timed out after 600.0 seconds (ReadTimeout)
Model: llama3.2
```

Root cause in the current design:

- complete long-form `YouTubeScript` requested in one structured Ollama call,
- LocalLLMProvider forced a minimum 600-second timeout.

---

## 7. Script Writer V21

V21 was created to replace giant single-call script generation with bounded chunks.

### Intended Flow

```text
7-minute target
      |
      +--> Chunk 1: hook + intro + first material
      |
      +--> Chunk 2: evidence section
      |
      +--> Chunk 3: evidence section
      |
      +--> Chunk 4: final material + conclusion + CTA
      |
      v
Merge into one YouTubeScript
```

### Design Goals

- 4 smaller structured LLM calls.
- Approx. 240–280 words per chunk.
- 90-second primary limit per chunk.
- 45-second compact rescue.
- No second full-script rewrite.
- Preserve evidence grounding and selected language.
- Remove the previous forced 600-second minimum behavior.

### Status

V21 patch artifact was prepared and validated in mock/runtime tests, but installation on the main project has not yet been reconfirmed here.

Verify V21 by looking for:

```text
[SCRIPT V21] chunk 1/4 ...
[SCRIPT V21] chunk 2/4 ...
[SCRIPT V21] chunk 3/4 ...
[SCRIPT V21] chunk 4/4 ...
```

---

## 8. Real Text-to-Video Experiment on M2 8 GB

### Model Tested

`Wan2.1-T2V-1.3B`

Test configuration:

- Apple MLX
- 4-bit quantization requested
- 416x240
- 17 frames
- 8 steps
- no cache

### Result

Model files downloaded successfully, including approximately:

```text
DiT transformer:  ~5.68 GB reconstructed
Wan VAE:          ~508 MB reconstructed
UMT5 XXL encoder: ~11.4 GB reconstructed
```

The process then ended with:

```text
zsh: killed
```

### Conclusion

`Wan2.1-T2V-1.3B` is not practical for the current 8 GB M2 in the tested MLX pipeline.

The main problem is total unified-memory pressure, especially the large text encoder.

Do not integrate this model into `run_auto.sh` on the current machine.

---

## 9. Recommended Video Strategy for M2 8 GB

Practical direction:

```text
llama3.2
   |
   v
scene planning
   |
   v
local still-image generation
   |
   +--> light scene motion / parallax
   +--> optional talking-character animation
   +--> optional frame interpolation
   |
   v
Piper voice
   |
   v
FFmpeg assembly
   |
   v
Final MP4
```

Potential lightweight components to evaluate separately:

- LivePortrait for talking-face/character animation,
- RIFE for frame interpolation,
- local parallax/depth motion,
- existing V4 scene motion.

If true diffusion video generation becomes mandatory, use a stronger self-hosted GPU worker rather than forcing it into 8 GB unified memory.

Do not describe pan/zoom/parallax output as full generative text-to-video.

---

## 10. Current Open Work

### Priority 1 — Script Writer Reliability

Confirm whether V21 is installed.

Expected log:

```text
[SCRIPT V21] chunk 1/4
```

### Priority 2 — Revalidate Fact Checker

After Script Writer succeeds, confirm clean-script behavior:

```text
[FACT] PASS: 0 material issue(s); repair=SKIPPED
```

For actual issues:

```text
issues > 0 -> repair once -> re-check
```

### Priority 3 — Reach Monetization Gate

Need one full successful workflow to validate:

- production scene-treatment diversity,
- content-originality heuristic,
- duration-aware narration check,
- disclosure review artifact,
- final monetization decision.

### Priority 4 — Visual Quality

Final MP4 should be checked for:

- repeated backgrounds,
- repeated compositions,
- slideshow feel,
- warped subjects,
- unrealistic placement,
- mismatched scene/story content,
- low-value motion,
- voice/scene mismatch.

### Priority 5 — Lightweight Motion

Do not spend more time forcing Wan2.1-T2V-1.3B into 8 GB memory.

Evaluate lighter animation approaches instead.

---

## 11. Design Principles

### Evidence First

Never extend script length by inventing:

- statistics,
- quotes,
- dates,
- motives,
- company responses,
- causal claims,
- event details.

### Real Duration

Narration length should determine realistic duration.

Do not label ~300 words as a seven-minute video.

### No Silent Quality Downgrade

If a true video-generation backend is requested but fails, do not silently replace it with a still-image zoom and call it generative video.

### Preserve Working Components

Prefer surgical fixes over rewriting whole agents.

### Transactional Patches

Patches should:

1. read current source,
2. transform in memory,
3. parse/compile,
4. back up originals,
5. commit only after precommit validation,
6. restore originals on failure,
7. remain idempotent.

---

## 12. Useful Commands

Run AUTO:

```bash
cd /Users/maa/agentic-content-factory && ./run_auto.sh
```

Search timeout configuration:

```bash
cd /Users/maa/agentic-content-factory && grep -RniE '600|timeout|ReadTimeout|api/generate' src/content_factory --include='*.py'
```

Compile project Python:

```bash
cd /Users/maa/agentic-content-factory && python3 -m compileall -q src/content_factory
```

---

## 13. Current Status Summary

| Area | Status |
|---|---|
| Real trend discovery | Working |
| Evidence enrichment | Working |
| Strategy grounding | Working |
| Growth strategy | Working |
| Local LLM | Working; long structured calls can hang |
| Script Writer | Needs V21 confirmation/end-to-end validation |
| Fact zero-issue logic | V20.4 fix prepared; revalidation pending |
| Monetization diversity | V20.x logic prepared; latest run did not reach gate |
| Piper/macOS voice | Available |
| Visual Engine V4 | Available |
| FFmpeg assembly | Available |
| Wan2.1 T2V on M2 8 GB | Tested and rejected due memory pressure |
| Full local generative video | Not practical on current 8 GB M2 |

---

## 14. Next Recommended Sequence

```text
1. Confirm/install Script Writer V21
2. Run AUTO workflow
3. Confirm 4 bounded script chunks
4. Confirm Fact Checker clean-pass behavior
5. Reach Content Production
6. Inspect monetization diversity preflight
7. Reach final Monetization Safety Gate
8. Review actual MP4 visually
9. Improve lightweight motion for M2 8 GB
```

This order keeps failures isolated and avoids changing script, fact-check, monetization, and video-generation systems simultaneously.
