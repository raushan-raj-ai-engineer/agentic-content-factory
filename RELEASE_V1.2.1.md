# v1.2.1 Theory-First Gate Fix

This maintenance release fixes a false-positive storyboard quality failure introduced by beginner-first pedagogy.

- EXPLAIN scenes intentionally use the theory-board grammar.
- FLOW scenes intentionally use the process-flow grammar.
- The diversity gate now reports raw lesson-wide layout dominance for diagnostics but hard-gates only flexible phases (hook, example, implementation, verify, recap, CTA).
- Adjacent semantic similarity and clone detection remain lesson-wide.
- Storyboard version: `study-storyboard-v7.1-theory-first`.
- Regression: 175 passed, 1 deselected (excluding optional live YouTube tests requiring yt_dlp).
