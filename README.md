# Agentic Content Factory

> **Version:** 1.2.1 — Theory-First Gate Fix  
> **Primary use case:** Generate long-form educational YouTube videos from a topic using a multi-agent AI workflow.  
> **Current study-video philosophy:** **Theory First → Flow Second → Example / Implementation → Verify / Recap**

Agentic Content Factory is a sequential multi-agent content-production system that can research a topic, create a strategy, write and review a script, fact-check it, design narration-grounded educational scenes, generate local narration, render semantic Manim animation, assemble a final YouTube video, create thumbnail variants, and produce growth / monetization-readiness reports.

The project is designed to make educational videos feel like **lessons**, not animated PowerPoint decks.

For Study Mode, the core rule is:

```text
HOOK
  ↓
THEORY FIRST
  ├─ Definition
  ├─ Key idea
  └─ Why it matters
  ↓
HOW IT FLOWS
  └─ Cause → Action → Result
  ↓
EXAMPLE / IMPLEMENTATION
  ↓
VERIFY / FAILURE CASES
  ↓
RECAP
```

The current release intentionally disables the old static-PNG-plus-zoom fallback for Study Mode. Educational scenes are expected to be rendered semantically with Manim.

---

## Table of Contents

1. [What This Project Does](#what-this-project-does)
2. [Current Release: v1.2.1](#current-release-v121)
3. [Core Features](#core-features)
4. [Study-Mode Teaching Architecture](#study-mode-teaching-architecture)
5. [End-to-End Multi-Agent Workflow](#end-to-end-multi-agent-workflow)
6. [System Architecture](#system-architecture)
7. [Requirements](#requirements)
8. [Quick Start](#quick-start)
9. [Recommended macOS Setup](#recommended-macos-setup)
10. [Environment Configuration](#environment-configuration)
11. [LLM Providers](#llm-providers)
12. [Voice System](#voice-system)
13. [Visual and Animation System](#visual-and-animation-system)
14. [Audio Mastering](#audio-mastering)
15. [Research and Topic Discovery](#research-and-topic-discovery)
16. [Running the Factory](#running-the-factory)
17. [CLI Reference](#cli-reference)
18. [Output Artifacts](#output-artifacts)
19. [Quality Gates](#quality-gates)
20. [Testing and Validation](#testing-and-validation)
21. [Project Structure](#project-structure)
22. [Bundled Advanced Engines](#bundled-advanced-engines)
23. [Troubleshooting](#troubleshooting)
24. [Recommended Workflow for New Users](#recommended-workflow-for-new-users)
25. [Version Evolution](#version-evolution)
26. [Known Limitations](#known-limitations)
27. [Security and Secrets](#security-and-secrets)
28. [Development Notes](#development-notes)

---

# What This Project Does

A normal AI content script may stop after generating text.

Agentic Content Factory continues through the complete production chain:

```text
Topic / Category
      ↓
Research
      ↓
Strategy
      ↓
Growth Planning
      ↓
Human Approval
      ↓
Script Generation
      ↓
Authenticity Review
      ↓
Retention Optimization
      ↓
Packaging / Title / Thumbnail Strategy
      ↓
Script Review
      ↓
Fact Check
      ↓
Script Approval
      ↓
Production Planning
      ↓
Study Animation Direction
      ↓
Production Approval
      ↓
Voice Generation
      ↓
Visual Generation
      ↓
Semantic Manim Rendering
      ↓
Video Assembly
      ↓
Audio Mastering
      ↓
Thumbnail Variants
      ↓
Growth Readiness
      ↓
Monetization Safety Review
      ↓
Final Artifacts
```

A successful run can produce:

- final MP4 video,
- narration audio,
- per-scene visuals,
- storyboard / production metadata,
- thumbnail A/B/C variants,
- final thumbnail,
- growth-readiness report,
- YouTube A/B plan,
- monetization-safety report,
- upload checklist,
- performance report,
- complete workflow result JSON.

---

# Current Release: v1.2.1

v1.2.1 is a maintenance release built on the **Theory-First** study architecture.

## Why v1.2 exists

Earlier versions could mark a scene as `phase=explain`, but visually still render it as another diagram containing agents, tools, nodes, arrows, or system components.

That made beginner lessons jump too quickly into architecture.

v1.2 introduced a real theory-rendering primitive.

Every substantive Study chapter now starts with:

1. **Definition** — what the concept means.
2. **Key idea** — the important distinction or mechanism.
3. **Why it matters** — why the learner should care.
4. **How it flows** — shown in the following narration window.

The current storyboard policy is:

```text
study-storyboard-v7.1-theory-first
```

The current animation/cache policy is:

```text
study-animation-v9-theory-first
```

## What v1.2.1 fixes

Beginner-first lessons intentionally reuse two pedagogical grammars:

```text
EXPLAIN → theory board
FLOW    → process flow
```

An older diversity gate could incorrectly treat this intentional teaching consistency as layout repetition.

v1.2.1 makes the layout-dominance gate **phase-aware**.

It still detects genuine repetition, but it does not reject a high-quality lesson merely because:

- EXPLAIN scenes consistently use theory boards, or
- FLOW scenes consistently use process-flow grammar.

Semantic clone detection and adjacent-scene similarity checks remain active.

---

# Core Features

## 1. Multi-agent production workflow

The application uses a sequential workflow with shared state.

Each agent performs one responsibility and passes structured information to the next stage.

This makes the system easier to debug than one giant prompt.

---

## 2. Exact-topic mode

Generate a lesson for a topic you provide:

```bash
bash run_topic.sh \
  --topic "AI Agents Explained for Beginners" \
  --duration-minutes 10 \
  --category ai
```

---

## 3. Automatic topic discovery

The system can discover topics by category.

Supported main CLI categories:

```text
technical
ai
software_testing
funny
entertainment
general
auto
```

Example:

```bash
bash run_topic.sh --category ai
```

Fully automatic cross-category discovery:

```bash
bash run_topic.sh --auto
```

---

## 4. Study Mode

Study Mode is automatically selected for:

```text
technical
ai
software_testing
```

It is also inferred from technical topic terms such as:

- AI / LLM / RAG,
- agents / agentic AI / MCP,
- programming languages,
- APIs,
- databases,
- cloud,
- Docker / Kubernetes,
- Git / GitHub,
- security,
- Playwright / Selenium / Pytest,
- testing / automation / DevOps,
- ML / deep learning,
- algorithms / data structures,
- frontend / backend.

Study Mode requires semantic Manim rendering.

---

## 5. Theory-first pedagogy

A Study lesson does not start by dumping a flowchart on the viewer.

The preferred structure is:

```text
WHAT IT MEANS
      ↓
HOW IT WORKS
      ↓
REAL EXAMPLE
      ↓
IMPLEMENTATION
      ↓
VERIFY / FAILURE
      ↓
RECAP
```

The EXPLAIN stage uses dedicated `theory_point` objects rather than generic architecture nodes.

---

## 6. Beginner-first scene planning

Each substantive chapter uses an explicit learning phase:

```text
hook
explain
flow
example
implementation
verify
recap
cta
```

This allows the renderer to choose a teaching grammar appropriate to the current learning purpose.

---

## 7. Narration-grounded visuals

Visual planning prioritizes:

```text
current narration
    ↓
current chapter
    ↓
overall topic
```

This prevents the overall topic from leaking the same generic visual into every scene.

Example:

If the topic is AI Agents but the current narration is explaining MCP, the intended visual should represent MCP/tool connectivity rather than simply showing another generic AI Agent circle.

---

## 8. Semantic animation

Motion is intended to explain meaning.

Examples:

```text
query      → type into a search field
documents  → split into chunks
embedding  → transform into vector / semantic space
retrieval  → scan and highlight closest matches
context    → merge evidence with the original question
agent      → choose a tool and observe the returned state
API        → request travels out and response travels back
code       → execute and show resulting state
```

Motion should not exist only to keep the screen moving.

---

## 9. Visual diversity controls

The storyboard and quality system tracks repetition.

The system can detect or penalize issues such as:

- adjacent semantic clones,
- repeated object topology,
- generic object overuse,
- placeholder labels,
- excessive layout dominance in flexible phases,
- overloaded scenes,
- repetitive composition.

Theory-board and process-flow repetition are treated differently because those can be intentional pedagogical structures.

---

## 10. Temporal narration lock

Scene visuals are tied to the narration window being spoken.

The system can remove visual elements that are introduced before narration supports them.

You may see logs such as:

```text
[TEMPORAL ALIGNMENT REPAIR] ...
```

---

## 11. Script quality gates

The pipeline does not blindly render any generated script.

Review stages check for:

- weak structure,
- repeated long sentences,
- low coherence,
- audience mismatch,
- generic or off-topic content,
- factual issues,
- poor teaching flow.

A repair pass may run before production.

If quality remains below the configured standard, the workflow may stop instead of spending time rendering a poor video.

---

## 12. Fact checking

Study scripts pass through a Fact Checker and Fact Check Gate before production.

The fact-check report is part of the workflow state and final result.

---

## 13. Growth optimization

The workflow includes:

- Growth Strategy,
- Retention Optimizer,
- Packaging Optimizer,
- Growth Readiness.

The packaging stage can create multiple title / thumbnail-text options.

The growth-readiness stage produces a report and YouTube A/B plan.

---

## 14. Thumbnail variants

The Thumbnail Generation Agent can generate:

```text
thumbnail_A.png
thumbnail_B.png
thumbnail_C.png
thumbnail.png
```

The final `thumbnail.png` is the default selected output.

---

## 15. Monetization-safety review

The workflow includes a monetization readiness / safety stage.

Outputs may include:

```text
monetization_report.json
YOUTUBE_UPLOAD_CHECKLIST.md
AI_DISCLOSURE_REVIEW.md
```

These are internal production aids, not guarantees of approval by YouTube or another platform.

---

## 16. Performance profiling

Every workflow agent is timed.

The final performance report helps identify bottlenecks such as:

- script generation,
- storyboard generation,
- voice generation,
- video rendering / assembly.

Failed runs also attempt to write a performance report.

---

## 17. Local-first operation

The project can use local components for several expensive production stages:

- Ollama for LLM inference,
- Kokoro / Piper / macOS voices,
- Manim for educational animation,
- FFmpeg for final video processing.

Cloud LLMs remain optional.

---

# Study-Mode Teaching Architecture

The central design goal is:

> A beginner should understand **what** a concept means before being shown **how** the system flows.

## Example: AI Agent

### Theory scene

```text
DEFINITION
An AI agent works toward a goal.

KEY IDEA
It can decide what action or tool to use next.

WHY IT MATTERS
It can complete multi-step work instead of returning one static response.
```

### Flow scene

```text
USER GOAL
    ↓
AI AGENT
    ↓
UNDERSTAND CURRENT STATE
    ↓
CHOOSE ACTION / TOOL
    ↓
EXECUTE
    ↓
OBSERVE RESULT
    ↓
GOAL COMPLETE?
    ├─ NO → repeat
    └─ YES → FINAL RESULT
```

### Example scene

```text
"Find today's weather"

User
 ↓
Agent
 ↓
Weather tool
 ↓
Observation
 ↓
Agent formats the answer
```

The same pedagogy can be adapted to programming, testing, algorithms, APIs, cloud, security, science-like technical concepts, and other structured learning topics.

---

# End-to-End Multi-Agent Workflow

The primary workflow currently runs these agents in sequence:

| # | Agent | Responsibility |
|---:|---|---|
| 1 | Research Planner Agent | Resolves exact-topic or discovery mode |
| 2 | Trend Research Agent | Finds / validates topic evidence and trend signals |
| 3 | Study Localization Agent | Sets language, locale and target market |
| 4 | Evidence Enrichment Agent | Adds evidence where appropriate |
| 5 | Content Strategist Agent | Creates audience, angle, hook and lesson strategy |
| 6 | Strategy Grounding Agent | Corrects drift and duration policy |
| 7 | Growth Strategy Agent | Plans retention / packaging opportunities |
| 8 | Human Approval Gate | Approves strategy |
| 9 | Script Writer Agent | Generates the long-form narration |
| 10 | Authenticity Review Agent | Checks generic / templated writing risk |
| 11 | Retention Optimizer Agent | Improves opening and engagement |
| 12 | Packaging Optimizer Agent | Creates titles / thumbnail packages |
| 13 | Script Reviewer Agent | Scores and repairs script quality |
| 14 | Fact Checker Agent | Checks factual reliability |
| 15 | Fact Check Gate | Blocks unsafe / weak factual output |
| 16 | Script Approval Gate | Approves final script |
| 17 | Content Production Agent | Segments narration and plans production |
| 18 | Study Animation Director Agent | Builds narration-driven storyboard |
| 19 | Production Approval Gate | Approves production plan |
| 20 | Model Memory Release Agent | Releases local LLM resources before media work |
| 21 | Voice Generation Agent | Generates narration |
| 22 | Visual Generation Agent | Generates scene backdrops / visual assets |
| 23 | Video Assembly Agent | Renders / combines scene animation and audio |
| 24 | Thumbnail Generation Agent | Builds thumbnail variants |
| 25 | Growth Readiness Agent | Scores content packaging readiness |
| 26 | Monetization Safety Gate | Produces upload/readiness checks |

The orchestration is intentionally sequential so each stage has a clear input/output contract.

---

# System Architecture

```text
                           ┌─────────────────────┐
                           │ Topic / Category    │
                           └──────────┬──────────┘
                                      │
                                      ▼
                        ┌──────────────────────────┐
                        │ Research + Trend Layer   │
                        └────────────┬─────────────┘
                                     │
                                     ▼
                        ┌──────────────────────────┐
                        │ Strategy + Growth Layer  │
                        └────────────┬─────────────┘
                                     │
                                     ▼
                        ┌──────────────────────────┐
                        │ Script Generation        │
                        │ Review + Fact Checking   │
                        └────────────┬─────────────┘
                                     │
                                     ▼
                        ┌──────────────────────────┐
                        │ Content Production Plan  │
                        └────────────┬─────────────┘
                                     │
                                     ▼
                  ┌───────────────────────────────────┐
                  │ Study Animation Director          │
                  │                                   │
                  │ narration → phase → storyboard    │
                  │ theory → flow → example → verify  │
                  └────────────────┬──────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │                             │
                    ▼                             ▼
          ┌──────────────────┐         ┌──────────────────┐
          │ Voice Generation │         │ Visual Assets    │
          │ Kokoro/Piper/etc │         │ deterministic    │
          └────────┬─────────┘         └────────┬─────────┘
                   │                            │
                   └──────────────┬─────────────┘
                                  ▼
                      ┌────────────────────────┐
                      │ Semantic Manim Render  │
                      └───────────┬────────────┘
                                  ▼
                      ┌────────────────────────┐
                      │ FFmpeg Assembly/QC     │
                      └───────────┬────────────┘
                                  ▼
                   ┌──────────────────────────────┐
                   │ Final MP4 + Reports + Thumb │
                   └──────────────────────────────┘
```

---

# Requirements

## Python

```text
Python >= 3.11
Python 3.12 recommended
```

The package metadata supports Python 3.11+.

---

## Required system tools for Study Mode

At minimum:

```text
FFmpeg
FFprobe
Manim dependencies
```

For local LLM usage:

```text
Ollama
```

For browser-assisted features:

```text
Playwright Chromium
```

---

## Main Python dependencies

Core:

- Pydantic
- pydantic-settings
- PyYAML
- HTTPX
- Pillow
- NumPy
- python-dotenv

Optional dependency groups:

```text
alignment → faster-whisper
browser   → playwright
channel   → manim + playwright
voice     → piper-tts + onnxruntime + kokoro-onnx + soundfile
research  → yt-dlp
dev       → pytest + pytest-asyncio + ruff + mypy
```

---

# Quick Start

## 1. Enter the project

```bash
cd /path/to/agentic-content-factory
```

## 2. Create / activate the virtual environment

The easiest supported setup:

```bash
bash setup.sh
```

For full Study Mode with semantic Manim:

```bash
bash setup_channel.sh --manim
```

## 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and configure at least one LLM provider.

## 4. Verify dependencies

```bash
.venv/bin/python scripts/doctor.py
```

## 5. Generate a Study video

```bash
bash run_topic.sh \
  --topic "AI Agents Explained for Beginners" \
  --duration-minutes 10 \
  --category ai
```

---

# Recommended macOS Setup

Study Mode is currently easiest to run on macOS because the repository includes Bash setup helpers and optional macOS voice fallback.

Install Homebrew if needed, then:

```bash
brew install ffmpeg cairo pkg-config
```

Create the environment and install full Study dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -e '.[voice,channel,alignment,research,dev]'
```

Install browser runtime:

```bash
python -m playwright install chromium
```

Check Manim:

```bash
python -m manim checkhealth
```

Check FFmpeg:

```bash
ffmpeg -version
ffprobe -version
```

---

# Environment Configuration

Start from:

```bash
cp .env.example .env
```

Do **not** commit `.env`.

## Recommended Study defaults

```dotenv
STUDY_BEGINNER_FIRST=true

STUDY_SCENE_MIN_WORDS=34
STUDY_SCENE_MAX_WORDS=48

STUDY_ACTIVE_CHECKS=false
STUDY_ACTIVE_CHECK_EVERY=4

STUDY_CAMERA_STYLE=auto
STUDY_MOTION_DENSITY=auto
STUDY_ENVIRONMENT=auto

STUDY_VIEWER_MARKET=US
```

## Recommended voice defaults

```dotenv
CONTENT_FACTORY_STUDY_VOICE_BACKEND=auto

KOKORO_MODEL_PATH=models/kokoro/kokoro-v1.0.fp16.onnx
KOKORO_VOICES_PATH=models/kokoro/voices-v1.0.bin

KOKORO_VOICE_US_MALE=am_michael
KOKORO_VOICE_US_FEMALE=af_bella

KOKORO_CHARACTER_VOICES=am_fenrir,am_puck,af_bella,af_nicole

CONTENT_FACTORY_VOICE_MAX_TEMPO=1.12
CONTENT_FACTORY_VOICE_MIN_TEMPO=0.90
```

## Study audio mastering

```dotenv
STUDY_AUDIO_MASTERING=1
STUDY_AUDIO_TARGET_LUFS=-16.0
STUDY_AUDIO_TRUE_PEAK_DBTP=-1.5
STUDY_AUDIO_LUFS_TOLERANCE=1.2
```

## Visual quality defaults

```dotenv
STUDY_ANIMATION_MIN_RETENTION=0.35

STUDY_MAX_EMPTY_FRAME_RATIO=0.03
STUDY_MIN_P10_OCCUPANCY=0.0075
STUDY_MIN_P25_OCCUPANCY=0.018
STUDY_MIN_FOREGROUND_LUMA=46
```

## Script-runtime resilience

```dotenv
CONTENT_FACTORY_SCRIPT_CHUNK_TIMEOUT=150
CONTENT_FACTORY_SCRIPT_RESCUE_TIMEOUT=90
CONTENT_FACTORY_SCRIPT_MICRO_TIMEOUT=75

CONTENT_FACTORY_OLLAMA_NUM_PREDICT=2400
CONTENT_FACTORY_OLLAMA_FAILOVER_ORDER=llama3.2,qwen2.5:3b,qwen3:4b,qwen,llama
```

## Word timing / alignment

```dotenv
STUDY_WORD_TIMING=auto
STUDY_WHISPER_MODEL=base
```

Install the optional alignment group:

```bash
python -m pip install -e '.[alignment]'
```

---

# LLM Providers

Supported providers:

```text
auto
ollama
gemini
openai
anthropic
compatible
```

`compatible` supports an OpenAI-compatible chat-completions endpoint.

## Provider locking

At the beginning of each run the application selects a provider/model and prints:

```text
[LLM LOCK] ...
```

The selected provider/model is used as the primary model for the workflow.

Retryable cloud failures can use bounded retry logic and, when configured, switch to local Ollama fallback.

---

## Local Ollama

Example:

```dotenv
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
```

Check installed models:

```bash
ollama list
```

Test Ollama:

```bash
curl http://localhost:11434/api/tags
```

---

## Gemini

```dotenv
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=your_supported_model_name
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta
```

Optional retry tuning:

```dotenv
GEMINI_HTTP_RETRIES=4
GEMINI_MIN_REQUEST_INTERVAL_SECONDS=2.0
```

If your account has strict RPM limits, increase the interval.

---

## OpenAI

```dotenv
LLM_PROVIDER=openai
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=your_model_name
OPENAI_BASE_URL=https://api.openai.com/v1
```

---

## Anthropic

```dotenv
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your_key_here
ANTHROPIC_MODEL=your_model_name
ANTHROPIC_BASE_URL=https://api.anthropic.com/v1
```

---

## OpenAI-compatible provider

```dotenv
LLM_PROVIDER=compatible
LLM_COMPATIBLE_BASE_URL=https://provider.example/v1
LLM_COMPATIBLE_API_KEY=your_key
LLM_COMPATIBLE_MODEL=your_model
```

A local compatible endpoint may not require an API key.

---

## Automatic provider selection

```dotenv
LLM_PROVIDER=auto
LLM_FALLBACK_ORDER=gemini,openai,anthropic,compatible,ollama
LLM_OLLAMA_FALLBACK=true
```

Only providers that are correctly configured should be expected to participate.

---

# Voice System

Supported main narration backends:

```text
auto
kokoro
piper
macos
```

## Recommended Study voice

For U.S.-focused educational content:

```text
locale: en-US
profile: us-male-warm
Kokoro default: am_michael
```

## List voices

```bash
bash run_topic.sh --list-voices
```

Or:

```bash
content-factory --list-voices
```

## Select backend

```bash
bash run_topic.sh \
  --topic "RAG Explained" \
  --voice-backend kokoro
```

## Select exact voice

```bash
bash run_topic.sh \
  --topic "RAG Explained" \
  --voice-backend kokoro \
  --voice am_michael
```

## Voice profiles

```text
us-male-warm
us-female-clear
auto
```

## Kokoro setup

The repository contains:

```bash
bash scripts/setup_kokoro_voice.sh
```

The configured model locations are:

```text
models/kokoro/kokoro-v1.0.fp16.onnx
models/kokoro/voices-v1.0.bin
```

## Piper

Piper remains supported as a local fallback.

Example helper:

```bash
bash scripts/download_voice.sh en_US-lessac-medium
```

## macOS fallback

If local neural voices are unavailable, Study Mode can fall back to an installed macOS voice.

For premium output, Kokoro is preferred when available.

---

# Visual and Animation System

## Study Mode requires Manim

Study Mode intentionally rejects the old static PNG + zoom fallback.

If Manim is missing, the CLI reports a setup error.

Recommended setup:

```bash
brew install cairo pkg-config ffmpeg
bash setup_channel.sh --manim
```

---

## Semantic visual primitives

The storyboard supports many semantic visual kinds, including newer teaching primitives such as:

```text
theory_point
book
search_ui
context_window
answer_panel
point_cloud
```

alongside technical primitives for:

- users,
- agents,
- models,
- tools,
- APIs,
- browser interaction,
- code,
- terminals,
- arrays,
- documents,
- databases,
- gates,
- shields,
- resources,
- packets,
- charts,
- vectors,
- and other diagram elements.

---

## Theory renderer

`phase=explain` is special.

It should render point-wise teaching content:

```text
Definition
Key idea
Why it matters
```

Process figures are intentionally avoided during the theory stage.

---

## Flow renderer

`phase=flow` is where process relationships become explicit.

Typical grammar:

```text
input
  ↓
decision
  ↓
action
  ↓
result
  ↓
next decision
```

The exact objects should come from current narration rather than generic topic keywords.

---

## Camera

Supported Study camera configuration values:

```text
auto
static
guided
follow
focus
cinematic
```

Set:

```dotenv
STUDY_CAMERA_STYLE=auto
```

The camera should move only when the motion improves understanding.

---

## Motion density

```text
auto
low
medium
high
```

Recommended:

```dotenv
STUDY_MOTION_DENSITY=auto
```

---

## Environments

Supported configured environment values include:

```text
auto
technical
data_space
code_lab
browser_space
document_space
analogy_warm
security_boundary
science_lab
clean_light
```

Recommended:

```dotenv
STUDY_ENVIRONMENT=auto
```

---

## Deterministic backdrops

Study Mode can generate deterministic vector backdrops.

Educational text is rendered through Manim rather than relying on diffusion-generated text.

Optional AI hero imagery is off by default:

```dotenv
CONTENT_FACTORY_STUDY_AI_HERO=0
```

---

## Render concurrency

Independent Manim scene processes can render in parallel.

Default:

```dotenv
CONTENT_FACTORY_STUDY_RENDER_PARALLEL=2
```

This is intentionally conservative for laptop stability.

---

# Audio Mastering

Final Study narration is normalized and quality-checked.

Default target:

```text
Integrated loudness: -16 LUFS
True peak:          -1.5 dBTP
```

Configuration:

```dotenv
STUDY_AUDIO_MASTERING=1
STUDY_AUDIO_TARGET_LUFS=-16.0
STUDY_AUDIO_TRUE_PEAK_DBTP=-1.5
STUDY_AUDIO_LUFS_TOLERANCE=1.2
```

Typical successful log:

```text
[AUDIO MASTER] ... qc=PASS
```

The chain can include speech-clarity processing before loudness normalization.

---

# Research and Topic Discovery

The research configuration supports:

```yaml
research:
  provider: youtube_local
  mode: auto
  category: technical
  lookback_days: 7
```

Optional research dependencies are installed with:

```bash
python -m pip install -e '.[research]'
```

which includes `yt-dlp`.

If a YouTube Data API key is available:

```dotenv
YOUTUBE_API_KEY=
YOUTUBE_MAX_RESULTS=20
YOUTUBE_TIMEOUT=30
```

Study Mode may prefer stable curriculum grounding instead of forcing a technical lesson into recent-news coverage.

---

# Running the Factory

## Exact AI topic

```bash
bash run_topic.sh \
  --topic "AI Agents Explained: How Agentic AI Actually Works" \
  --duration-minutes 10 \
  --category ai
```

## Software-testing topic

```bash
bash run_topic.sh \
  --topic "Playwright Auto-Waiting Explained for Beginners" \
  --duration-minutes 8 \
  --category software_testing
```

## Technical topic

```bash
bash run_topic.sh \
  --topic "Docker Containers Explained Visually" \
  --duration-minutes 9 \
  --category technical
```

## Choose Gemini explicitly

```bash
bash run_topic.sh \
  --topic "MCP Explained for Beginners" \
  --category ai \
  --llm-provider gemini
```

## Choose local Ollama

```bash
bash run_topic.sh \
  --topic "RAG Explained for Beginners" \
  --category ai \
  --llm-provider ollama \
  --llm-model llama3.2
```

## Set locale

```bash
bash run_topic.sh \
  --topic "API Testing Explained" \
  --category software_testing \
  --locale en-US
```

## Verbose workflow result

```bash
bash run_topic.sh \
  --topic "Vector Databases Explained" \
  --category ai \
  --verbose-result
```

---

# CLI Reference

Primary CLI:

```bash
content-factory -h
```

Main options:

```text
--config PATH
--topic TEXT
--category {technical,ai,software_testing,funny,entertainment,general,auto}
--auto

--llm-provider {auto,ollama,gemini,openai,anthropic,compatible}
--llm-model MODEL

--locale LOCALE
--duration-minutes N

--voice-backend {auto,kokoro,piper,macos}
--voice-profile {us-male-warm,us-female-clear,auto}
--voice VOICE
--list-voices

--verbose-result
```

## Important shell quoting rule

Use normal ASCII quotes:

```bash
--topic "AI Agents Explained"
```

Do not use smart quotes:

```text
“AI Agents Explained”
```

Smart quotes are not shell delimiters and can produce:

```text
error: unrecognized arguments
```

---

# Output Artifacts

Typical output structure:

```text
artifacts/
└── <topic-slug>/
    └── <run-id>/
        ├── audio/
        │   ├── voice_manifest.json
        │   └── ...
        │
        ├── visuals/
        │   ├── scene_1.png
        │   ├── scene_2.png
        │   └── ...
        │
        ├── video/
        │   └── final_video.mp4
        │
        ├── thumbnail/
        │   ├── thumbnail_A.png
        │   ├── thumbnail_B.png
        │   ├── thumbnail_C.png
        │   └── thumbnail.png
        │
        ├── growth/
        │   ├── growth_readiness_report.json
        │   └── YOUTUBE_AB_TEST_PLAN.md
        │
        ├── monetization/
        │   ├── monetization_report.json
        │   ├── YOUTUBE_UPLOAD_CHECKLIST.md
        │   └── AI_DISCLOSURE_REVIEW.md
        │
        ├── performance/
        │   └── performance_report.json
        │
        └── workflow_result.json
```

Exact files can vary by mode and enabled features.

---

# Final Video Quality

The current local Study-video pipeline reports:

```text
1080p30
H.264
CRF17
BT.709
```

Final assembly includes visual QC and audio QC.

The renderer also tracks animation retention using frame decimation so a video cannot pass solely because one still image is held for long periods.

---

# Quality Gates

The project intentionally contains multiple gates because generating a complete 8–12 minute video is expensive.

It is better to fail before rendering than produce an unusable video.

## Script gate

Checks may include:

- coherence,
- structure,
- audience fit,
- repetitive writing,
- topic specificity,
- malformed text,
- unsupported claims.

---

## Fact gate

Checks factual reliability before production.

---

## Pedagogy gate

For beginner Study content, verifies chapter structure such as:

```text
explain → flow
```

---

## Storyboard semantic gate

Checks:

- specialization,
- generic-object ratio,
- scene similarity,
- clone patterns,
- phase correctness,
- layout diversity where diversity is expected.

v1.2.1 makes layout dominance phase-aware.

---

## Deterministic fallback protection

When structured LLM storyboard output cannot be produced, deterministic rescue can be used.

The engine is designed to avoid silently turning most of a premium lesson into generic deterministic templates.

---

## Temporal-alignment repair

Removes visuals not yet supported by narration.

---

## Final visual QC

Checks include concepts such as:

- empty-frame ratio,
- foreground occupancy,
- readability / foreground brightness,
- animation retention.

Example environment settings:

```dotenv
STUDY_MAX_EMPTY_FRAME_RATIO=0.03
STUDY_MIN_P10_OCCUPANCY=0.0075
STUDY_MIN_P25_OCCUPANCY=0.018
STUDY_MIN_FOREGROUND_LUMA=46
STUDY_ANIMATION_MIN_RETENTION=0.35
```

---

## Audio QC

Default target:

```text
-16 LUFS
-1.5 dBTP true peak
```

---

# Testing and Validation

Install development dependencies:

```bash
python -m pip install -e '.[dev]'
```

## Study-focused tests

```bash
pytest -q tests -k "study"
```

## Broad local suite

When optional live YouTube tests are unavailable:

```bash
pytest -q \
  --ignore=tests/manual/test_youtube_live.py \
  --ignore=tests/test_youtube_research.py
```

## Ruff

```bash
ruff check .
```

## MyPy

```bash
mypy src
```

The project uses strict MyPy configuration.

## Python compile check

```bash
python -m compileall -q src tests
```

## Current v1.2.1 regression status

The release validation recorded:

```text
175 passed
1 deselected
```

excluding optional live YouTube checks that require the `yt-dlp` environment.

---

# Project Structure

High-level layout:

```text
agentic-content-factory/
├── .env.example
├── README.md
├── pyproject.toml
├── configs/
├── docs/
├── models/
├── scripts/
├── src/
│   └── content_factory/
│       ├── agents/
│       ├── cartoon/
│       ├── channel/
│       ├── config/
│       ├── human/
│       ├── llm/
│       ├── local_video/
│       ├── models/
│       ├── monetization/
│       ├── orchestration/
│       ├── performance/
│       ├── research/
│       ├── thumbnail/
│       ├── utils/
│       ├── video/
│       ├── visual/
│       └── voice/
├── tests/
├── run_topic.sh
├── run_auto.sh
├── run_cartoon.sh
├── run_own_video.sh
├── channel.sh
├── setup.sh
└── setup_channel.sh
```

---

## Important source areas

### `src/content_factory/agents/`

Workflow business stages:

- research planning,
- trend research,
- localization,
- strategy,
- script,
- review,
- fact checking,
- animation direction,
- voice,
- visuals,
- video assembly,
- thumbnails,
- growth,
- monetization.

### `src/content_factory/visual/`

Study storyboard contracts and semantic Manim scene rendering.

Important current files include:

```text
study_storyboard.py
study_manim_scene.py
```

### `src/content_factory/video/`

Final Study rendering / FFmpeg assembly and media QC.

### `src/content_factory/voice/`

Local voice provider integration.

### `src/content_factory/llm/`

Provider selection, structured output, runtime fallback and model integrations.

### `src/content_factory/orchestration/`

Sequential workflow execution and shared state.

### `src/content_factory/performance/`

Per-agent profiling and reports.

---

# Bundled Advanced Engines

The repository contains additional experimental / specialized production paths.

New users should start with `run_topic.sh`.

---

## 1. Channel / deterministic lesson engine

Entry point:

```bash
bash channel.sh
```

The channel CLI includes DSA-oriented lesson tooling with renderers such as:

```text
manim
cards
```

It also contains browser-demo support.

This is useful for deterministic educational demonstrations separate from the main long-form Study workflow.

---

## 2. Cartoon engine

Entry point:

```bash
bash run_cartoon.sh
```

The repository includes cartoon configurations for:

- characters,
- language profiles,
- backgrounds,
- routes,
- rigs,
- visual quality,
- monetization,
- performance.

Language configuration files include examples for:

```text
English
Hindi
Hinglish
Magahi
Bhojpuri
```

This is a separate production path from the main Study Mode.

---

## 3. Open-source local video engine

Entry point:

```bash
bash run_own_video.sh
```

The local-video CLI is an experimental local media engine.

Its code includes support paths for motion backends such as:

```text
SVD
AnimateDiff
LTX
```

and optional lip-sync routing.

These workflows are hardware-dependent and are not required for the normal Study Mode.

---

# Troubleshooting

## Study Mode says Manim is required

Error resembles:

```text
Study Mode now requires semantic Manim rendering.
```

Fix on macOS:

```bash
brew install cairo pkg-config ffmpeg
bash setup_channel.sh --manim
```

Then:

```bash
python -m manim checkhealth
```

---

## `ffmpeg` not found

macOS:

```bash
brew install ffmpeg
```

Verify:

```bash
ffmpeg -version
ffprobe -version
```

---

## Smart quotes break the CLI

Wrong:

```bash
--topic “AI Agents Explained”
```

Correct:

```bash
--topic "AI Agents Explained"
```

---

## Gemini HTTP 429

A rate-limit log may look like:

```text
HTTP 429 rate-limit
```

Options:

1. Allow the configured retry policy to run.
2. Increase request spacing:

```dotenv
GEMINI_MIN_REQUEST_INTERVAL_SECONDS=4.0
```

3. Configure Ollama fallback.
4. Run with local Ollama explicitly.

---

## Cloud LLM timeout

Script generation uses chunked generation and bounded retries.

Relevant settings:

```dotenv
CONTENT_FACTORY_SCRIPT_CHUNK_TIMEOUT=150
CONTENT_FACTORY_SCRIPT_RESCUE_TIMEOUT=90
CONTENT_FACTORY_SCRIPT_MICRO_TIMEOUT=75
```

The pipeline may switch to a configured Ollama fallback for retryable cloud failures.

---

## Storyboard JSON generation fails

The Study Animation Director can:

- retry structured output,
- rescue scenes individually,
- use deterministic fallback where safe,
- reject the entire storyboard if semantic quality falls below the required gate.

A small number of rescued scenes is not automatically fatal.

---

## `one layout dominates the lesson`

If you are on an older v1.2 build, upgrade to v1.2.1.

Verify:

```bash
grep -R "study-storyboard-v7.1-theory-first" src/content_factory -n
```

v1.2.1 makes layout-dominance checking phase-aware.

---

## Theory scene still looks like a process diagram

Verify the current theory renderer:

```bash
grep -R '"theory_point"' src/content_factory -n
```

Also verify:

```bash
grep -R "study-animation-v9-theory-first" src/content_factory -n
```

For an EXPLAIN scene, storyboard objects should be theory-oriented instead of generic agent/tool/model nodes.

---

## Old scene appears again

Study rendering uses versioned cache policies.

After major renderer changes, verify the active policy version.

If you are manually copying old sidecar/cache directories, remove the stale generated cache before comparing releases.

Do not delete your `.env`.

---

## Voice suddenly changes speaker

For English Study Mode, prefer Kokoro and keep character inserts in the Kokoro voice family:

```dotenv
CONTENT_FACTORY_STUDY_VOICE_BACKEND=auto
KOKORO_CHARACTER_VOICES=am_fenrir,am_puck,af_bella,af_nicole
```

---

## Voice sounds unnaturally fast

Current defaults limit automatic tempo adjustment:

```dotenv
CONTENT_FACTORY_VOICE_MAX_TEMPO=1.12
CONTENT_FACTORY_VOICE_MIN_TEMPO=0.90
```

---

## ONNX Runtime `constant_folding` warnings

Kokoro / ONNX may emit warnings about reciprocal nodes and constant folding.

If narration is still generated correctly, these warnings are generally not the same as a workflow failure.

Use the actual `[VOICE]`, `[ARTIFACT]`, and final exit status to determine whether the stage failed.

---

## No YouTube research support

Install:

```bash
python -m pip install -e '.[research]'
```

Verify:

```bash
python -c "import yt_dlp; print('yt-dlp OK')"
```

---

## `pytest` cannot collect YouTube tests

If `yt_dlp` is intentionally not installed, exclude optional live/research tests:

```bash
pytest -q \
  --ignore=tests/manual/test_youtube_live.py \
  --ignore=tests/test_youtube_research.py
```

---

## Ollama is not detected

Verify:

```bash
ollama list
```

and:

```bash
curl http://localhost:11434/api/tags
```

Default endpoint:

```dotenv
OLLAMA_BASE_URL=http://localhost:11434
```

---

# Recommended Workflow for New Users

Do not start by changing renderer internals.

Use this sequence.

## Step 1 — verify machine

```bash
python3 --version
ffmpeg -version
ollama list
```

## Step 2 — setup

```bash
bash setup_channel.sh --manim
```

## Step 3 — configure `.env`

For the simplest local-first workflow:

```dotenv
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2

CONTENT_FACTORY_STUDY_VOICE_BACKEND=auto

STUDY_BEGINNER_FIRST=true
STUDY_ACTIVE_CHECKS=false
STUDY_CAMERA_STYLE=auto
STUDY_MOTION_DENSITY=auto
STUDY_ENVIRONMENT=auto
```

Or configure one supported cloud provider.

## Step 4 — run tests

```bash
pytest -q tests -k "study"
```

## Step 5 — create a short test lesson first

```bash
bash run_topic.sh \
  --topic "AI Agents Explained for Beginners" \
  --duration-minutes 5 \
  --category ai
```

## Step 6 — inspect logs

Look for:

```text
[LLM LOCK]
[SCRIPT]
[REVIEW]
[FACT]
[STUDY PEDAGOGY]
[STUDY STORYBOARD]
[VOICE]
[STUDY MANIM]
[AUDIO MASTER]
[STUDY VISUAL QC]
[ARTIFACT]
```

## Step 7 — inspect the actual MP4

Do not trust numeric QC alone.

Check:

- Does theory appear before architecture?
- Does narration match the visual on screen?
- Does each scene add new understanding?
- Does a diagram show cause → action → result?
- Are labels readable on mobile?
- Is the same scene composition overused?
- Are code scenes tied to execution state?
- Does the recap reconstruct the learner's mental model?

## Step 8 — only then render a long video

```bash
bash run_topic.sh \
  --topic "AI Agents Explained: How Agentic AI Actually Works in 2026" \
  --duration-minutes 10 \
  --category ai
```

---

# Version Evolution

This project evolved through repeated review of real rendered videos.

## v0.8 — Premium semantic motion

Major direction:

- semantic Manim scenes,
- real animation beats,
- camera system,
- richer visual primitives,
- removed static-PNG-primary rendering,
- disabled old zoom-on-still behavior.

Lesson learned:

> Motion alone does not guarantee teaching clarity.

---

## v0.9 — Teaching-directed

Focus:

- one teaching idea per scene,
- cause → action → result,
- stronger narration-to-visual grounding,
- no forced Pause & Predict cards by default,
- new primitives such as search UI, book, context window, answer panel and point cloud,
- better code-to-state relationships,
- improved RAG-style semantic teaching.

Lesson learned:

> Visuals must explain the narration, not merely decorate it.

---

## v1.0 — Content-first

Focus:

- stronger script quality gates,
- improved cloud-failure handling,
- storyboard fallback protection,
- better content-first QC,
- prevent weak fallback output from silently becoming a final long-form video.

Lesson learned:

> A beautiful renderer cannot rescue a weak script or generic storyboard.

---

## v1.1 — Beginner-first

Focus:

```text
WHAT IT MEANS
→ HOW IT FLOWS
→ EXAMPLE / IMPLEMENTATION
→ VERIFY / RECAP
```

Added explicit learning phases and shorter Study narration windows.

Lesson learned:

> A learner needs a mental model before a system diagram.

---

## v1.2 — Theory-first

Focus:

- `theory_point` primitive,
- Definition,
- Key idea,
- Why it matters,
- process figures forbidden during EXPLAIN,
- theory-first renderer and cache version.

Lesson learned:

> `phase=explain` must change actual rendering behavior, not just metadata.

---

## v1.2.1 — Phase-aware gate fix

Focus:

- preserve intentional theory-board consistency,
- preserve intentional flow grammar,
- diversity gate only hard-gates layout dominance in flexible phases,
- clone / similarity detection remains lesson-wide.

---

# Known Limitations

## 1. Quality gates cannot replace human review

A video can pass numeric checks and still feel boring or confusing.

Always review the final MP4.

## 2. Manim is mandatory for Study Mode

Static image + zoom is intentionally not used as a Study fallback.

## 3. Cloud APIs can rate-limit

Gemini / OpenAI / Anthropic behavior depends on the configured account and model.

## 4. Local small LLMs may produce weaker structured output

The system contains rescue and deterministic fallback logic, but high-quality script/storyboard generation still depends on model capability.

## 5. Local video diffusion is hardware-dependent

The optional local video engine is separate from the normal semantic Study renderer and can require much more memory/GPU capability.

## 6. Platform readiness reports are advisory

Growth and monetization reports help production review; they do not guarantee views, retention, monetization approval, or policy compliance.

## 7. Setup scripts are Unix/Bash oriented

The primary tested workflow is macOS / Bash.

Windows users can use WSL or manually install equivalent Python/native dependencies, but platform-specific shell behavior may differ.

---

# Security and Secrets

Never commit:

```text
.env
API keys
OAuth credentials
tokens
private certificates
downloaded private data
```

Recommended `.gitignore` entries include:

```gitignore
.env
.env.*
!.env.example

.venv/
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/

artifacts/
logs/

credentials/
secrets/
token.json
credentials.json
```

Keep `.env.example` free of real secrets.

---

# Development Notes

## Install editable development environment

```bash
python -m pip install -e '.[voice,channel,alignment,research,dev]'
```

## Common quality commands

```bash
ruff check .
mypy src
pytest -q
python -m compileall -q src tests
```

## Study-focused validation

```bash
pytest -q tests -k "study"
```

## Inspect current storyboard version

```bash
grep -R "study-storyboard-v7.1-theory-first" src/content_factory -n
```

## Inspect current animation version

```bash
grep -R "study-animation-v9-theory-first" src/content_factory -n
```

## Inspect theory primitive

```bash
grep -R '"theory_point"' src/content_factory -n
```

---

# Useful Helper Scripts

The repository includes scripts for setup, diagnostics, reports and experimental testing.

Useful starting points:

```text
scripts/doctor.py
scripts/setup_kokoro_voice.sh
scripts/download_voice.sh
scripts/preview_voice.sh
scripts/show_growth_report.sh
scripts/show_monetization_report.sh
scripts/show_performance_report.sh
scripts/show_artifacts.sh
scripts/cache_status.sh
scripts/clear_logs.sh
```

Many additional scripts under `scripts/` are development/regression tools and are not required for normal use.

---

# Final Production Checklist

Before publishing a generated educational video, verify:

- [ ] Topic is specific and beginner-appropriate.
- [ ] Hook promises a clear learning outcome.
- [ ] Theory appears before the main process diagram.
- [ ] Definition is understandable without prior expert knowledge.
- [ ] Key idea explains the important distinction.
- [ ] “Why it matters” connects the concept to a real need.
- [ ] Flow diagram follows the actual narration.
- [ ] Example is relatable.
- [ ] Code, if present, shows execution state rather than static text only.
- [ ] No repeated scene remains on screen too long.
- [ ] Same generic figure is not reused across unrelated ideas.
- [ ] Labels are readable on mobile.
- [ ] Narration pace sounds natural.
- [ ] Audio mastering passes.
- [ ] Visual QC passes.
- [ ] Fact check passes.
- [ ] Thumbnail is readable at small size.
- [ ] Growth / monetization reports have been reviewed.
- [ ] Final MP4 has been watched by a human before upload.

---

# Philosophy

The project should not optimize for:

> “How many things are moving?”

It should optimize for:

> **“Can a beginner understand the narrator by watching the screen?”**

The preferred visual contract is:

```text
Explain the idea
      ↓
Show the relationship
      ↓
Demonstrate the mechanism
      ↓
Apply it
      ↓
Verify understanding
```

That is the standard for every future Study Mode improvement.
