# v1.2 Theory-First Study Video

## Why this release exists

The v1.1 pipeline assigned `learning_phase=explain`, but EXPLAIN scenes were still rendered as semantic figures. In the reviewed output this made the lesson jump from the hook directly into agent/tool/goal diagrams. A beginner never received a clean point-by-point theory explanation first.

## New invariant

Every substantive study chapter starts with:

1. **Definition** — what the concept means in plain language.
2. **Key idea** — the important distinction/mechanism to remember.
3. **Why it matters** — why the learner should care.
4. **How it flows** — only in the next narration window, render the process/flow diagram.

The theory points are derived from the exact current narration window. Process figures are forbidden in the EXPLAIN phase. The renderer uses dedicated `theory_point` cards and a static teaching-board camera.

The render/cache policy is versioned as `study-animation-v9-theory-first` so older v1.1 scene caches cannot silently replace the new theory-first visuals.
