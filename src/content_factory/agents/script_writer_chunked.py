from __future__ import annotations

import asyncio
import os
from typing import Any

from pydantic import BaseModel, Field

from content_factory.models.content import YouTubeScript
from content_factory.modes import is_study_mode


class _ChunkSection(BaseModel):
    title: str
    content: str


class _ScriptChunk(BaseModel):
    title: str = ""
    hook: str = ""
    introduction: str = ""
    sections: list[_ChunkSection] = Field(default_factory=list)
    conclusion: str = ""
    call_to_action: str = ""


class _MicroSection(BaseModel):
    title: str
    content: str


_ScriptChunk.model_rebuild()
_MicroSection.model_rebuild()


def _bounded_env(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(low, min(high, value))


def _clip(text: Any, limit: int) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[:limit].rsplit(" ", 1)[0] + " …"


def _call_text(agent: Any, name: str, *args: Any, limit: int = 2200) -> str:
    fn = getattr(agent, name, None)
    if not callable(fn):
        return ""
    try:
        return _clip(fn(*args), limit)
    except Exception:
        return ""


def _compact_context(agent: Any, state: Any) -> str:
    topic = state.topic or state.strategy.topic
    if is_study_mode(state):
        parts = [
            "AUTHORITATIVE TECHNICAL FACTS\n" + _call_text(agent, "_authoritative_facts", topic, limit=2600),
            "TOPIC / CURRICULUM GROUNDING\n" + _call_text(agent, "_grounding_context", state, limit=1600),
        ]
    else:
        parts = [
            "AUTHORITATIVE FACTS\n" + _call_text(agent, "_authoritative_facts", topic, limit=1800),
            "TREND/NEWS EVIDENCE\n" + _call_text(agent, "_trend_evidence", state, limit=2300),
            "ENRICHED NEWS\n" + _call_text(agent, "_enriched_evidence", state, limit=2300),
            "TOPIC GROUNDING\n" + _call_text(agent, "_grounding_context", state, limit=1600),
            "YOUTUBE DISCOVERY\n" + _call_text(agent, "_youtube_evidence", state, limit=1400),
        ]
    return "\n\n".join(part for part in parts if part.strip())


async def _generate_one(
    agent: Any,
    *,
    prompt: str,
    system_prompt: str,
    timeout: float,
) -> _ScriptChunk:
    async def invoke() -> _ScriptChunk:
        try:
            return await agent._llm.generate_structured(
                prompt,
                _ScriptChunk,
                system_prompt=system_prompt,
                max_retries=0,
            )
        except TypeError as exc:
            # Compatibility with another provider implementing the base interface
            # without the LocalLLMProvider max_retries extension.
            if "max_retries" not in str(exc):
                raise
            return await agent._llm.generate_structured(
                prompt,
                _ScriptChunk,
                system_prompt=system_prompt,
            )

    return await asyncio.wait_for(invoke(), timeout=timeout)


def _prior_context(chunks: list[_ScriptChunk]) -> str:
    if not chunks:
        return "No prior chunk."
    titles: list[str] = []
    tail = ""
    for chunk in chunks:
        for section in chunk.sections:
            if section.title.strip():
                titles.append(section.title.strip())
            if section.content.strip():
                tail = section.content.strip()[-500:]
    return (
        "Already-covered section titles: "
        + (", ".join(titles[-6:]) if titles else "none")
        + "\nTail of prior narration for continuity: "
        + (tail or "none")
    )


def _word_count_text(text: str) -> int:
    return len([token for token in text.replace("\n", " ").split(" ") if token.strip()])


def _chunk_word_count(chunk: _ScriptChunk) -> int:
    values = [
        chunk.hook,
        chunk.introduction,
        *(section.content for section in chunk.sections),
        chunk.conclusion,
        chunk.call_to_action,
    ]
    return sum(_word_count_text(value) for value in values)


def _build_prompt(
    agent: Any,
    state: Any,
    *,
    index: int,
    target_words: int,
    context: str,
    chunks: list[_ScriptChunk],
    rescue: bool,
    total_chunks: int | None = None,
) -> str:
    strategy = state.strategy
    language = agent._target_language_name(state)
    low = max(120, round(target_words * (0.78 if rescue else 0.88)))
    high = round(target_words * (1.05 if rescue else 1.12))

    study_mode = is_study_mode(state)
    if total_chunks is None:
        total_chunks = 6 if study_mode else 4
    if study_mode:
        roles = {
            1: (
                "Opening teaching chunk. Provide title, hook, introduction, and exactly one substantive section. "
                "Start with an informative 10-24 word hook that states a concrete learner problem plus the mechanism/payoff. Immediately after the hook, give a THEORY-FIRST explanation in exactly three short declarative ideas: (1) plain-language definition, (2) key idea or distinction, (3) why it matters/usefulness. Only after those three ideas may you introduce the mechanism or flow. Never use a generic rhetorical opener such as 'Have you ever wondered', 'Did you know', 'What if', or 'Imagine'. "
                "Do not provide conclusion or call_to_action yet."
            ),
            2: (
                "Mental-model chunk. Leave title/hook/introduction/conclusion/call_to_action empty. "
                "Provide exactly one new substantive section that teaches a simple analogy/mental model and one concrete example."
            ),
            3: (
                "Architecture chunk. Leave title/hook/introduction/conclusion/call_to_action empty. "
                "Provide exactly one new substantive section explaining the step-by-step architecture, data flow, or mechanism with a worked trace."
            ),
            4: (
                "Implementation chunk. Leave title/hook/introduction/conclusion/call_to_action empty. "
                "Provide exactly one new substantive section covering practical implementation or usage. Map the earlier mental model to variables, functions, conditions, or components when code is useful."
            ),
            5: (
                "Verification chunk. Leave title/hook/introduction/conclusion/call_to_action empty. "
                "Provide exactly one new substantive section covering testing/verification plus concrete failure cases, edge cases, or limitations."
            ),
            6: (
                "Closing teaching chunk. Leave title/hook/introduction empty. Provide exactly one final substantive section with tradeoffs or an interview/practical takeaway, then a concise recap, learner practice task, and natural call_to_action. Do not repeat earlier sections."
            ),
        }
    else:
        roles = {
            1: (
                "Opening chunk. Provide title, hook, introduction, and exactly one substantive section. "
                "Do not provide conclusion or call_to_action yet."
            ),
            2: (
                "Evidence chunk A. Leave title/hook/introduction/conclusion/call_to_action empty. "
                "Provide exactly two new substantive sections grounded only in the supplied evidence."
            ),
            3: (
                "Evidence chunk B. Leave title/hook/introduction/conclusion/call_to_action empty. "
                "Provide exactly two new sections covering evidence not already covered. Separate confirmed facts "
                "from uncertainty; do not speculate."
            ),
            4: (
                "Closing chunk. Leave title/hook/introduction empty. Provide one final substantive section, "
                "a concise conclusion, and a natural call_to_action. Do not repeat earlier sections."
            ),
        }


    rescue_note = (
        "This is a compact rescue attempt. Prefer fewer sentences and strict evidence fidelity. "
        if rescue
        else ""
    )

    mode_policy = (
        """
STUDY MODE POLICY
This is an evergreen technical lesson. Stable technical definitions, architecture, algorithms, code behavior, and common engineering practices may be explained from established technical knowledge and the authoritative fact pack. Trend/news material is optional discovery context only. Do not make current-event claims unless explicitly supported.
"""
        if study_mode
        else """
CURRENT MODE POLICY
This is an evidence-bounded current-topic narration. Time-sensitive claims must stay inside supplied evidence.
"""
    )

    return f"""
Create CHUNK {index} OF {total_chunks} of one YouTube narration.

{mode_policy}

TOPIC: {strategy.topic}
USER-REQUESTED SCOPE: {state.metadata.get("requested_topic", strategy.topic)}
AUDIENCE: {strategy.audience}
ANGLE: {strategy.angle}
TARGET LANGUAGE: {language}
WHOLE-VIDEO TARGET: approximately {state.metadata.get('topic_grounding', {}).get('target_duration_minutes', strategy.estimated_duration_minutes)} minutes
THIS CHUNK SPOKEN LENGTH: approximately {low}-{high} words

CHUNK ROLE
{roles[index]}

APPROVED KNOWLEDGE / GROUNDING CONTEXT
{context}

CONTINUITY
{_prior_context(chunks)}

RULES
1. {rescue_note}Write every viewer-facing field in {language}.
2. Never invent dates, scores, quotes, motives, statistics, current releases, adoption claims, or causal claims. Stable technical fundamentals are allowed in study mode; time-sensitive specifics are not.
3. A headline proves only what the headline explicitly says; discovery evidence must not replace technical teaching.
4. In current mode, use cautious phrases such as "reports say" for report-level evidence. In study mode, omit unnecessary news framing and teach the stable concept directly.
5. Do not mention internal trend scores, search volumes, candidate ranks, or pipeline mechanics.
6. Do not repeat a point already covered in CONTINUITY.
7. Natural spoken narration, not article prose; no filler.
8. For educational/technical topics, write as a subject-matter expert for a beginner unless the audience explicitly says advanced: learner problem → plain-language definition/theory → prerequisite/context → one simple analogy or mental model when useful → worked example/flow → implementation/details → verification → concrete edge cases/tradeoffs → practical takeaway.
9. BEGINNER MINI-ARC FOR EVERY SUBSTANTIVE SECTION: start with 2-4 short sentences explaining WHAT the concept means and why it matters. Then transition into HOW IT FLOWS with a concrete cause → action → result sequence. Only then move to example/code/verification. This order is mandatory because visuals are rendered as EXPLAIN first and FLOW second.
10. For AI topics, define important terms before using them repeatedly and explain the data/control flow before code, libraries, or framework names.
11. For technical explanations, prefer short sentences and explicit transitions such as "why this works", "what changes next", and "how to verify it". Do not mechanically read code or diagrams.
12. When code is shown, explicitly map earlier reasoning to the relevant variable, condition, function, or line so a beginner understands why the code exists.
13. Use concrete edge examples with expected behavior when the evidence/problem definition supports them; do not list only labels like "empty input" or "boundary case".
14. Do not force quiz questions or rhetorical questions between sections. Engagement should come from examples, visual cause/effect and progressive reveals.
15. Do not use hype or unsupported superlatives. Precise terminology is more important than excitement.
16. If USER-REQUESTED SCOPE explicitly names subtopics/facets, preserve that scope across the six chunks. Do not replace requested facets with repeated generic examples.
17. Return only the structured JSON fields. For fields not used by this chunk, return empty string or [].
"""


async def _expand_study_chunk_if_short(
    agent: Any,
    state: Any,
    *,
    index: int,
    total_chunks: int,
    chunk: _ScriptChunk,
    target_words: int,
    context: str,
    prior_chunks: list[_ScriptChunk],
    timeout: float,
) -> _ScriptChunk:
    current_words = _chunk_word_count(chunk)
    if not is_study_mode(state) or current_words >= round(target_words * 0.90):
        return chunk
    language = agent._target_language_name(state)
    low = round(target_words * 0.94)
    high = round(target_words * 1.08)
    prompt = f"""
Expand this SAME study-script chunk from {current_words} words to approximately {low}-{high} words.
Do not create a different outline and do not rewrite already-good material. Preserve all populated fields and section titles; add depth inside them.

CURRENT CHUNK
{chunk.model_dump_json(indent=2)}

APPROVED GROUNDING
{context}

PRIOR CONTINUITY
{_prior_context(prior_chunks)}

RULES
- Write only in {language}.
- Add useful mechanism explanation, worked trace, implementation reasoning, verification, or concrete edge cases.
- No filler, repeated definitions, unsupported current facts, statistics, quotes, or hype.
- Return only the structured chunk JSON.
"""
    system = (
        "You deepen an existing educational script chunk without changing its role or factual boundary. "
        "Return only valid structured JSON."
    )
    try:
        expanded = await _generate_one(
            agent, prompt=prompt, system_prompt=system, timeout=timeout
        )
    except Exception as exc:
        print(
            f"[SCRIPT V23] chunk {index}/{total_chunks} targeted-depth=SKIP "
            f"({exc.__class__.__name__})"
        )
        return chunk
    expanded_words = _chunk_word_count(expanded)
    if expanded_words > current_words:
        print(
            f"[SCRIPT V23] chunk {index}/{total_chunks} targeted-depth=PASS "
            f"words={current_words}->{expanded_words}"
        )
        return expanded
    return chunk


def _looks_like_timeout(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    text = str(exc).casefold()
    return "timeout" in text or "timed out" in text


async def _recover_llm_after_timeout(llm: Any, reason: str) -> bool:
    """Prefer one-way provider/model failover before retrying a slow chunk."""
    force = getattr(llm, "force_fallback", None)
    if callable(force):
        try:
            if await force(reason):
                return True
        except Exception as exc:
            print(f"[SCRIPT V23] runtime provider failover unavailable ({exc.__class__.__name__})")

    switch = getattr(llm, "switch_to_alternate_model", None)
    if callable(switch):
        try:
            return bool(await switch(reason))
        except Exception as exc:
            print(f"[SCRIPT V23] local model failover unavailable ({exc.__class__.__name__})")
    return False


def _micro_title(index: int, total_chunks: int) -> str:
    if total_chunks == 6:
        return {
            1: "Core concept",
            2: "Mental model",
            3: "Architecture and flow",
            4: "Implementation",
            5: "Verification and failure cases",
            6: "Tradeoffs and practical takeaway",
        }.get(index, f"Part {index}")
    return f"Part {index}"


async def _micro_rescue_chunk(
    agent: Any,
    state: Any,
    *,
    index: int,
    total_chunks: int,
    target_words: int,
    context: str,
    chunks: list[_ScriptChunk],
    timeout: float,
) -> _ScriptChunk:
    """Generate one compact section with a much smaller schema and prompt."""
    language = agent._target_language_name(state)
    topic = state.topic or state.strategy.topic
    title_hint = _micro_title(index, total_chunks)
    compact_context = _clip(context, 2200)
    prior = _clip(_prior_context(chunks), 800)
    words = max(110, min(220, round(target_words * 0.62)))
    prompt = f"""
Write one compact narration section for CHUNK {index} OF {total_chunks}.

TOPIC: {topic}
SECTION PURPOSE: {title_hint}
TARGET LANGUAGE: {language}
TARGET LENGTH: about {words} words

APPROVED GROUNDING
{compact_context}

CONTINUITY
{prior}

RULES
- Return exactly one structured section with title and content.
- Teach one concrete mechanism/example only; do not repeat prior material.
- Short spoken sentences. No filler, hype, unsupported current facts, statistics, or quotes.
- For study content, map input -> transformation -> output -> verification when useful.
"""
    system = (
        "You are a concise subject-matter expert rescuing one timed-out educational "
        "section. Return only valid structured JSON."
    )

    async def invoke() -> _MicroSection:
        try:
            return await agent._llm.generate_structured(
                prompt,
                _MicroSection,
                system_prompt=system,
                max_retries=0,
            )
        except TypeError as exc:
            if "max_retries" not in str(exc):
                raise
            return await agent._llm.generate_structured(
                prompt, _MicroSection, system_prompt=system
            )

    section = await asyncio.wait_for(invoke(), timeout=timeout)
    chunk = _ScriptChunk(sections=[_ChunkSection(title=section.title, content=section.content)])
    if index == 1:
        chunk.title = state.strategy.topic
        chunk.hook = state.strategy.hook
    if index == total_chunks:
        chunk.conclusion = (
            "Recap the mechanism in your own words, then verify it with one small example "
            "before adding more complexity."
        )
        chunk.call_to_action = "Try the practice task, then compare your result with the mechanism you just learned."
    return chunk


def _deterministic_continuity_chunk(
    state: Any,
    *,
    index: int,
    total_chunks: int,
) -> _ScriptChunk:
    """Last-resort study continuation that adds no time-sensitive factual claim."""
    topic = state.topic or state.strategy.topic
    title = _micro_title(index, total_chunks)
    content = (
        f"For {topic}, keep the mechanism visible as you work: identify the input, "
        "follow the transformation one step at a time, inspect the output, and verify it "
        "against the requirement. Use one small example first. If the result differs from "
        "what you expected, check the boundary between steps instead of adding more "
        "complexity. This gives you a repeatable way to reason about the system and test "
        "whether each stage is doing the job you intended."
    )
    chunk = _ScriptChunk(sections=[_ChunkSection(title=title, content=content)])
    if index == 1:
        chunk.title = state.strategy.topic
        chunk.hook = state.strategy.hook
    if index == total_chunks:
        chunk.conclusion = "Keep the mental model simple: trace the input, transformation, output, and verification."
        chunk.call_to_action = "Practice the flow on one small example before moving to a larger implementation."
    return chunk


async def generate_chunked_script(
    agent: Any,
    state: Any,
    *,
    min_words: int,
    max_words: int,
    target_minutes: int,
) -> YouTubeScript:
    """Generate a long script with bounded, resumable semantic chunks.

    Study mode uses six smaller calls so 3B/4B local models do not need to emit
    400-500 word structured payloads in one request. A timeout can trigger a
    one-way runtime provider/model failover, then compact micro-rescue.
    """
    primary_timeout = _bounded_env(
        "CONTENT_FACTORY_SCRIPT_CHUNK_TIMEOUT", 90.0, 45.0, 150.0
    )
    rescue_timeout = _bounded_env(
        "CONTENT_FACTORY_SCRIPT_RESCUE_TIMEOUT", 45.0, 30.0, 90.0
    )

    study_mode = is_study_mode(state)
    target_wpm = 144 if study_mode else 150
    desired_total = max(min_words, min(max_words, target_minutes * target_wpm))
    weights = (0.18, 0.17, 0.17, 0.17, 0.16, 0.15) if study_mode else (0.23, 0.27, 0.27, 0.23)
    targets = [max(150, round(desired_total * weight)) for weight in weights]
    total_chunks = len(targets)
    micro_timeout = _bounded_env(
        "CONTENT_FACTORY_SCRIPT_MICRO_TIMEOUT", 75.0, 30.0, 120.0
    )
    language = agent._target_language_name(state)
    context = _compact_context(agent, state)
    chunks: list[_ScriptChunk] = []
    outer_timeout_count = 0
    failover_after_timeouts = max(1, min(4, int(os.getenv("CONTENT_FACTORY_SCRIPT_TIMEOUTS_BEFORE_FAILOVER", "2"))))

    print(
        f"[SCRIPT V23] chunked generation: chunks={total_chunks}; desired≈{desired_total} words; "
        f"primary_timeout={primary_timeout:.0f}s; rescue_timeout={rescue_timeout:.0f}s; "
        f"micro_timeout={micro_timeout:.0f}s"
    )

    for index, target in enumerate(targets, start=1):
        prompt = _build_prompt(
            agent,
            state,
            index=index,
            total_chunks=total_chunks,
            target_words=target,
            context=context,
            chunks=chunks,
            rescue=False,
        )
        system = (
            "You are a subject-matter-expert YouTube educator operating as one chunk of a larger script. "
            f"Write only in {language}. Teach mechanisms clearly, never invent current facts, and return only valid structured JSON. "
            + (
                "For evergreen technical study content, use established technical knowledge and prioritize beginner understanding over news commentary."
                if is_study_mode(state)
                else "For current topics, keep time-sensitive claims evidence-bounded."
            )
        )
        try:
            chunk = await _generate_one(
                agent,
                prompt=prompt,
                system_prompt=system,
                timeout=primary_timeout,
            )
            print(
                f"[SCRIPT V23] chunk {index}/{total_chunks} primary=PASS words={_chunk_word_count(chunk)}"
            )
        except Exception as primary_exc:
            switched_after_primary = False
            if _looks_like_timeout(primary_exc):
                outer_timeout_count += 1
                # One slow cloud call must not downgrade the entire production run
                # to a small local model. First retry this chunk with the compact
                # rescue prompt on the same provider. Only repeated outer timeouts
                # are allowed to activate provider failover.
                if outer_timeout_count >= failover_after_timeouts:
                    switched_after_primary = await _recover_llm_after_timeout(
                        agent._llm,
                        f"script chunk {index}/{total_chunks} repeated primary timeouts ({outer_timeout_count})",
                    )
            print(
                f"[SCRIPT V23] chunk {index}/{total_chunks} primary=FAIL "
                f"({primary_exc.__class__.__name__}); "
                + ("failover active; compact rescue" if switched_after_primary else "same-provider compact rescue")
            )
            rescue_prompt = _build_prompt(
                agent,
                state,
                index=index,
                total_chunks=total_chunks,
                target_words=max(150, round(target * 0.78)),
                context=context,
                chunks=chunks,
                rescue=True,
            )
            try:
                chunk = await _generate_one(
                    agent,
                    prompt=rescue_prompt,
                    system_prompt=system,
                    timeout=rescue_timeout,
                )
                print(
                    f"[SCRIPT V23] chunk {index}/{total_chunks} rescue=PASS words={_chunk_word_count(chunk)}"
                )
            except Exception as rescue_exc:
                reason = (
                    f"script chunk {index}/{total_chunks} timed out after "
                    f"primary={primary_timeout:.0f}s rescue={rescue_timeout:.0f}s"
                )
                switched = switched_after_primary
                if not switched and _looks_like_timeout(rescue_exc):
                    switched = await _recover_llm_after_timeout(agent._llm, reason)
                if switched:
                    print(
                        f"[SCRIPT V23] chunk {index}/{total_chunks} failover=ACTIVE; "
                        "trying micro-rescue"
                    )
                else:
                    print(
                        f"[SCRIPT V23] chunk {index}/{total_chunks} micro-rescue after "
                        f"{rescue_exc.__class__.__name__}"
                    )
                try:
                    chunk = await _micro_rescue_chunk(
                        agent,
                        state,
                        index=index,
                        total_chunks=total_chunks,
                        target_words=target,
                        context=context,
                        chunks=chunks,
                        timeout=micro_timeout,
                    )
                    print(
                        f"[SCRIPT V23] chunk {index}/{total_chunks} micro-rescue=PASS "
                        f"words={_chunk_word_count(chunk)}"
                    )
                except Exception as micro_exc:
                    if not is_study_mode(state):
                        raise RuntimeError(
                            f"Script chunk {index}/{total_chunks} failed primary, rescue, "
                            f"and micro-rescue: {micro_exc.__class__.__name__}: {micro_exc}"
                        ) from micro_exc
                    chunk = _deterministic_continuity_chunk(
                        state, index=index, total_chunks=total_chunks
                    )
                    print(
                        f"[SCRIPT V23] chunk {index}/{total_chunks} deterministic-continuity=PASS "
                        f"after {micro_exc.__class__.__name__}; workflow continues"
                    )
        chunk = await _expand_study_chunk_if_short(
            agent,
            state,
            index=index,
            total_chunks=total_chunks,
            chunk=chunk,
            target_words=target,
            context=context,
            prior_chunks=chunks,
            timeout=rescue_timeout,
        )
        chunks.append(chunk)

    title = next((c.title.strip() for c in chunks if c.title.strip()), state.strategy.topic)
    hook = next((c.hook.strip() for c in chunks if c.hook.strip()), state.strategy.hook)
    introduction = next((c.introduction.strip() for c in chunks if c.introduction.strip()), "")
    conclusion = next((c.conclusion.strip() for c in reversed(chunks) if c.conclusion.strip()), "")
    call_to_action = next(
        (c.call_to_action.strip() for c in reversed(chunks) if c.call_to_action.strip()),
        "",
    )

    sections: list[dict[str, str]] = []
    seen_titles: set[str] = set()
    for chunk in chunks:
        for section in chunk.sections:
            title_key = section.title.strip().casefold()
            if not section.content.strip() or title_key in seen_titles:
                continue
            seen_titles.add(title_key)
            sections.append(
                {"title": section.title.strip() or f"Part {len(sections) + 1}", "content": section.content.strip()}
            )

    if not sections:
        raise RuntimeError("Chunked Script Writer produced no usable sections.")

    script = YouTubeScript.model_validate(
        {
            "title": title,
            "hook": hook,
            "introduction": introduction,
            "sections": sections,
            "conclusion": conclusion,
            "call_to_action": call_to_action,
            "estimated_duration_minutes": target_minutes,
        }
    )

    print(
        f"[SCRIPT V23] merged chunks={total_chunks}; sections={len(sections)}; "
        "full_script_rewrite=DISABLED"
    )
    return script
