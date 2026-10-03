# SME Study Video Standard

This project treats Tech/AI/coding study videos as teaching products, not narrated slides.

## Required learning arc

Use the following arc unless the topic genuinely needs a different order:

1. **Concrete hook/problem** — give the learner a reason to care or a question to solve.
2. **Mental model** — explain the mechanism and assumptions before syntax or implementation detail.
3. **Worked state/flow** — show what changes step by step. Narration should match visible changes.
4. **Implementation/detail** — connect code, commands, architecture components, or model behavior to the mental model.
5. **Verification** — show how the learner can prove the result is correct: test, assertion, trace, metric, or evidence check.
6. **Complexity/tradeoff** — derive the cost or tradeoff from the mechanism when relevant.
7. **Edge cases/failure modes** — challenge assumptions and boundaries rather than showing only the happy path.
8. **Practice/recall** — ask the learner to predict or explain before running the answer.

## Narration standard

- Technical/study scenes should normally land around **145–160 WPM**.
- Use short spoken sentences. Insert a reasoning pause before an important conclusion.
- Explain **why** a step is valid before stating **what** changes.
- Do not read code, formulas, JSON, or diagrams mechanically.
- Define specialized terminology when it first becomes necessary.
- Avoid filler, generic welcomes, hype, unsupported superlatives, and repeated conclusions.
- Keep one dense reasoning unit per scene; split scenes rather than accelerating narration.

## Visual standard

- Final technical/study output is **1920×1080**.
- One frame should communicate one teaching idea.
- Prefer state transitions, pointer movement, eliminated options, data flow, before/after views, and test results over paragraphs.
- On-screen code must be readable on a phone. Show only the lines needed for the current teaching beat when possible.
- A technical architecture visual should show a meaningful causal flow such as `input → context → model → verify`, not decorative boxes.
- Use callouts to reinforce the reasoning, not to duplicate the narration word for word.

## AI-specific teaching standard

For AI, RAG, agents, evaluation, and model-testing topics, make the system boundary explicit. A strong lesson normally distinguishes:

- input/prompt
- retrieved or supplied context
- model or agent decision
- tool/API action when present
- observable output
- evaluation/verification signal
- failure mode (hallucination, bad retrieval, prompt injection, tool error, stale data, etc.) when relevant

Do not imply that an LLM response is correct merely because it is fluent. Demonstrate how correctness, grounding, safety, or task completion is checked.

## Coding/testing-specific teaching standard

For algorithms, automation, APIs, CI/CD, databases, and test architecture:

- state the input/contract
- show the changing state or data flow
- connect visual variables to code variables
- explain the invariant or reason the method works
- show a deterministic check/assertion
- cover at least one boundary condition when relevant

## Quality gate

The DSA channel runs a deterministic pedagogy review in `content_factory.channel.pedagogy`. It validates teaching structure and scene readability. It does **not** replace factual review or human publication review.
