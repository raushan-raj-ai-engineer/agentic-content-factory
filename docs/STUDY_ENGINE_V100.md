# Study engine v1.0.0 — content-first production gate

## Why v1.0 exists

The real AI Agents v0.9 render exposed a pipeline-level failure: the renderer was technically healthy, but a transient cloud timeout switched the run to a small local model. That fallback produced repetitive script sections, malformed storyboard JSON, and many deterministic generic scenes. Existing QC still passed because it measured motion and contrast more strongly than teaching clarity.

## v1.0 fixes

- One cloud timeout no longer downgrades the whole run. Script generation retries a compact prompt on the same provider first; provider failover requires repeated outer timeouts.
- Quality-critical stages can re-arm the primary provider at stage boundaries.
- The user's exact explicit topic/scope is preserved separately from a shortened display title so requested facets are not silently lost.
- Study scripts have a deterministic coherence gate for placeholder headings, repeated long sentences, repeated boilerplate openings, near-duplicate sections, and broken tokenization.
- A low-scoring study script gets one coherence repair; if it still fails, the workflow stops before expensive voice/render work.
- Current-looking numeric examples such as unsourced “today” temperatures are rejected by deterministic fact checks.
- Storyboard batching adapts to the active provider. Ollama defaults to one scene per structured request.
- Production refuses to continue when too many scenes require deterministic storyboard fallback.
- AI-agent lessons get a dedicated content-first visual profile: goal/action/result, tool selection, agent loop, context/memory, MCP, multi-agent handoffs, varied verification failure modes, tradeoffs, and code linked to live state.
- Storyboard QC now penalizes placeholder labels, overloaded scenes, layout dominance, and high adjacent semantic similarity.
- Renderer framing is tighter and educational-object scaling is larger.
- Final visual QC now requires meaningful median frame occupancy; the v0.9 AI Agents render's ~4.8% median occupancy would no longer pass.
- Safe packaging titles avoid constructions like “How ... Works Works.”

## Production philosophy

A video is not production-ready merely because it moves. The pipeline must preserve topic scope, produce a coherent script, create topic-grounded storyboards, use visually distinct teaching operations, and occupy the frame well enough to be understood on a phone. If the system cannot meet those conditions after bounded repair, it should stop rather than render a low-quality 11-minute video.

## Validation

- Python compileall: PASS
- Content-first regression tests: PASS
- Available non-live suite: 166 passed, 1 deselected
- Live YouTube tests were not collected because optional `yt_dlp` is not installed in the packaging environment.

The final acceptance test remains an actual render on the creator machine with the same AI Agents topic.
