# Agentic Content Factory - Phase 1 patch

This patch keeps the existing architecture and fixes the parts that can be
safely changed with the files currently provided.

## What it fixes

- `configs/local.yaml` is now actually loaded.
- Human approval can run automatically (`auto`), interactively (`manual`) or
  bypassed (`skip`).
- YouTube trend research no longer requires `YOUTUBE_API_KEY` or YouTube Data
  API. It uses local `yt-dlp` execution against public YouTube pages.
- Supports exact topic, category-driven discovery, and full auto mode.
- Trend scoring uses recency, views/hour and engagement instead of raw views.
- Workflow does not print `[DONE]` after an agent exception.
- Content production creates much shorter narration/visual pairs and strongly
  enforces scene/voice ID alignment while preserving the current model schema.
- SD-Turbo generation retries at M2-friendlier resolutions and clears MPS cache.

## Install/update local dependencies

From the project's existing environment:

```bash
pip install -U yt-dlp pyyaml accelerate
```

Also add `yt-dlp` and `PyYAML` to `pyproject.toml` dependencies when you send
that file for the final patch.

## Apply

Copy the files in this patch over the same relative paths in the project.
Keep a git commit/backup first.

## Run modes

Exact topic:

```bash
content-factory --topic "Playwright MCP"
```

Agent discovers a technical topic:

```bash
content-factory --category technical
```

Funny/viral discovery:

```bash
content-factory --category funny
```

Cross-category auto discovery:

```bash
content-factory --auto
```

Or configure defaults in `configs/local.yaml`.

## Still required for Phase 2

The current `ContentProductionPlan` model is stored in
`src/content_factory/models/content.py`, which was not included in the upload.
That model must be changed before replacing the two parallel arrays
(`voice_segments` and `visual_scenes`) with a single `beats` model.

For true custom local voice cloning, Piper must be replaced/augmented. Piper is
currently a fixed pre-trained voice. The recommended Phase 2 design is an
OpenVoice V2 worker in a separate Python 3.9 environment, called locally by the
main factory. This avoids dependency conflicts with the factory's Python 3.13
environment.

Files needed to complete Phase 2 exactly against the project:

- `src/content_factory/models/content.py`
- `src/content_factory/agents/human_gate.py`
- `src/content_factory/agents/script_approval_gate.py`
- `src/content_factory/agents/production_approval_gate.py`
- `src/content_factory/agents/fact_check_gate.py`
- `src/content_factory/agents/visual_generator.py`
- `src/content_factory/agents/video_assembler.py`
- `src/content_factory/thumbnail/local.py`
- `pyproject.toml`

A clean voice sample will also be needed to test the clone once the local voice
worker is wired in.
