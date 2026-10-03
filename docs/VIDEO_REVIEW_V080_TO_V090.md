# Real-output review: v0.8 → v0.9

Basis: the generated ~11-minute v0.8 RAG video supplied after the first premium-motion upgrade.

## What was wrong in the actual video

- `User Query` remained the dominant anchor through many unrelated sections.
- Multiple scenes began with one isolated card on a mostly empty canvas.
- Technical relationships were represented by repeated boxes even when the narration used a relatable mental model.
- Moving payloads did not communicate *what* was moving.
- The `PAUSE & PREDICT` card appeared during narration and visually covered the lower part of the scene.
- The open-book chapter did not feel like a person using an open book; it looked like another RAG diagram.
- Four code scenes looked like the same code treatment rather than progressive execution states.
- Architecture scenes did not clearly hand the result of one stage into the next stage.

## v0.9 response

v0.9 does not add decorative particles or random zooms. It changes the teaching model:

**one focal idea → one visible action → one visible consequence**.

The goal is that a viewer can mute the video briefly and still infer the conceptual relationship from the visual action, while the narration provides the precise explanation.

### Final directing pass

A final v0.9 pass added three hard editorial constraints: one teaching idea per scene, relationship-first cause/action/result staging, and continuity without carrying the same generic anchor through unrelated scenes. The architecture handoff now makes the selected retrieval result visibly become input to context construction. The closing `What to Watch Next` scene is narration-driven instead of being overwritten by another RAG flow diagram.
