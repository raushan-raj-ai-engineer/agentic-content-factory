from __future__ import annotations

import asyncio
import os
from typing import Any

from pydantic import BaseModel, Field

from content_factory.models.content import YouTubeScript


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


_ScriptChunk.model_rebuild()


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
) -> str:
    strategy = state.strategy
    language = agent._target_language_name(state)
    low = max(120, round(target_words * (0.78 if rescue else 0.88)))
    high = round(target_words * (1.05 if rescue else 1.12))

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

    return f"""
Create CHUNK {index} OF 4 of one evidence-bounded YouTube narration.

TOPIC: {strategy.topic}
AUDIENCE: {strategy.audience}
ANGLE: {strategy.angle}
TARGET LANGUAGE: {language}
WHOLE-VIDEO TARGET: approximately {state.metadata.get('topic_grounding', {}).get('target_duration_minutes', strategy.estimated_duration_minutes)} minutes
THIS CHUNK SPOKEN LENGTH: approximately {low}-{high} words

CHUNK ROLE
{roles[index]}

APPROVED EVIDENCE / GROUNDING
{context}

CONTINUITY
{_prior_context(chunks)}

RULES
1. {rescue_note}Write every viewer-facing field in {language}.
2. Never invent dates, scores, lineups, quotes, injuries, motives, outcomes, statistics, or causal claims.
3. A headline proves only what the headline explicitly says; do not infer match events or results.
4. Use cautious phrases such as "reports say" when evidence is report-level rather than definitive.
5. Do not mention internal trend scores, search volumes, candidate ranks, or pipeline mechanics.
6. Do not repeat a point already covered in CONTINUITY.
7. Natural spoken narration, not article prose; no filler.
8. Return only the structured JSON fields. For fields not used by this chunk, return empty string or [].
"""


async def generate_chunked_script(
    agent: Any,
    state: Any,
    *,
    min_words: int,
    max_words: int,
    target_minutes: int,
) -> YouTubeScript:
    """Generate a long script as four bounded local-LLM calls.

    This intentionally avoids one 900-1200-word Ollama request on small-memory
    Apple Silicon. Each call has a hard asyncio timeout and one compact rescue.
    """
    primary_timeout = _bounded_env(
        "CONTENT_FACTORY_SCRIPT_CHUNK_TIMEOUT", 90.0, 45.0, 150.0
    )
    rescue_timeout = _bounded_env(
        "CONTENT_FACTORY_SCRIPT_RESCUE_TIMEOUT", 45.0, 30.0, 90.0
    )

    desired_total = max(min_words, min(max_words, target_minutes * 150))
    weights = (0.23, 0.27, 0.27, 0.23)
    targets = [max(170, round(desired_total * weight)) for weight in weights]
    language = agent._target_language_name(state)
    context = _compact_context(agent, state)
    chunks: list[_ScriptChunk] = []

    print(
        f"[SCRIPT V21] chunked generation: chunks=4; desired≈{desired_total} words; "
        f"primary_timeout={primary_timeout:.0f}s; rescue_timeout={rescue_timeout:.0f}s"
    )

    for index, target in enumerate(targets, start=1):
        prompt = _build_prompt(
            agent,
            state,
            index=index,
            target_words=target,
            context=context,
            chunks=chunks,
            rescue=False,
        )
        system = (
            "You are an evidence-bounded YouTube script writer operating as one chunk of a larger script. "
            f"Write only in {language}. Never invent facts. Return only valid structured JSON."
        )
        try:
            chunk = await _generate_one(
                agent,
                prompt=prompt,
                system_prompt=system,
                timeout=primary_timeout,
            )
            print(
                f"[SCRIPT V21] chunk {index}/4 primary=PASS words={_chunk_word_count(chunk)}"
            )
        except Exception as primary_exc:
            print(
                f"[SCRIPT V21] chunk {index}/4 primary=FAIL "
                f"({primary_exc.__class__.__name__}); compact rescue"
            )
            rescue_prompt = _build_prompt(
                agent,
                state,
                index=index,
                target_words=max(170, round(target * 0.78)),
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
                    f"[SCRIPT V21] chunk {index}/4 rescue=PASS words={_chunk_word_count(chunk)}"
                )
            except Exception as rescue_exc:
                raise RuntimeError(
                    f"Script chunk {index}/4 failed bounded primary ({primary_timeout:.0f}s) "
                    f"and rescue ({rescue_timeout:.0f}s): {rescue_exc.__class__.__name__}: {rescue_exc}"
                ) from rescue_exc
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
        f"[SCRIPT V21] merged chunks=4; sections={len(sections)}; "
        "full_script_rewrite=DISABLED"
    )
    return script
