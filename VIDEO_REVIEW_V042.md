# Video review that drove the v0.5.0 study-engine reset

Reviewed artifact: the 8:01 MCP video produced by v0.4.2.

## What was wrong

The v0.4.2 video had real frame motion, but it still read visually like a slide deck. The motion-retention metric (81%) was therefore a false proxy for teaching quality.

Observed issues:

- Large repeated scene titles made every cut feel like a new PowerPoint slide.
- Most visual vocabulary was the same rounded rectangles + arrows regardless of concept.
- Labels were extracted as sentence fragments (`MCP.If`, `this deep dive`, `developer looking`, `After`) instead of concrete domain nouns.
- The kitchen analogy was not illustrated as a kitchen/chef/pantry mapping; it collapsed to generic boxes and an approximately-equals sign.
- Architecture scenes repeated the same graph composition instead of evolving from component setup to request travel to returned context.
- Code scenes displayed generic word fragments, not a real/pseudo execution sequence.
- The tiny `scene reference` inset repeated on every scene and added clutter without teaching value.
- Meaningful animation often completed early, leaving the remainder of narration with repeated emphasis pulses.
- The final motion gate measured pixel change, not whether motion explained the narration.

## v0.5.0 design response

v0.5.0 replaces fixed archetype templates as the primary planner with a narration-driven storyboard DSL. The same locked LLM used by the writing workflow creates concrete objects and teaching beats before the LLM is released. Generated Python is never executed.

Each Study Mode scene now contains:

- a purpose statement,
- a scene layout,
- 3-10 typed visual objects,
- concrete labels derived from the current narration,
- 4-12 narration-aligned beats,
- scene-specific reference keywords,
- a signature used for cross-scene repetition checks.

Typed objects include client, server, agent, model, tool, resource, prompt, file, document, database, vector store, browser, terminal, code, array, packet, shield, gate, table, balance and more.

Animation beats include reveal, connect, send/return, move, transform, code stepping, allow/reject, compare, select and replace. The renderer distributes these beats across the actual audio duration instead of finishing in the first few seconds and filling time with repetitive pulses.

The old giant slide title is replaced by a compact context bar. Scene-specific PNG art becomes faint ambient reference art rather than a repeated bottom-right screenshot. Whole-frame zoom remains disabled.

## Cross-topic guardrail

The storyboard director receives the exact narration of every scene and is explicitly prohibited from copying one generic diagram treatment across scenes or topics. It also receives recent storyboard signatures so adjacent scenes do not repeat the same layout/object/action pattern. If the LLM storyboard fails, the deterministic fallback still emits the same finite storyboard DSL instead of reverting to static PNG or zoom/pan.
