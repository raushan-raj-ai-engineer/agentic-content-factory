# Fact-check normalization — v0.6.6

This release fixes a false-block condition where an LLM could return a success/status sentence inside the `issues` array, for example:

`No material false or unsupported current claims remain.`

The previous gate treated every non-empty issue string as a real defect, forcing `approved=false` and capping the score at 70.

v0.6.6 now:

- filters only a narrow allowlist of explicit no-issue status sentences;
- preserves deterministic and actionable fact-check issues;
- normalizes contradictory `approved=false` + no-issue-only payloads to an approved result;
- keeps the existing safety rule that a plain rejected result with an empty issue list is still blocked;
- strengthens the LLM prompt so passing checks must return `issues=[]`.
