from __future__ import annotations

import re
from collections import Counter
from itertools import combinations

from content_factory.models.content import YouTubeScript

_STOP = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with",
    "this", "that", "is", "are", "was", "were", "be", "it", "as", "at", "by",
    "from", "into", "then", "than", "you", "your", "we", "our", "they", "their",
}
_PLACEHOLDER_TITLE = re.compile(
    r"^(?:part|section|chapter|topic|step)\s*(?:\d+|[ivx]+)?(?:\s*[-—:]\s*\d+)?$",
    re.IGNORECASE,
)
_BROKEN_HYPHEN = re.compile(r"\b[a-zA-Z]{2,}-\s+[a-zA-Z]\b")


def _norm_sentence(value: str) -> str:
    value = value.casefold().replace("’", "'")
    value = re.sub(r"[^\w\s']+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _sentences(value: str) -> list[str]:
    return [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+|\n+", value)
        if part.strip()
    ]


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_'-]{2,}", value.casefold())
        if token not in _STOP
    }


def study_script_quality_report(script: YouTubeScript) -> dict[str, object]:
    """Deterministic coherence/repetition checks for educational scripts.

    This intentionally complements the LLM reviewer. It catches production
    defects that a judge model can overlook: placeholder headings, copied
    boilerplate, near-duplicate sections and broken tokenization.
    """
    sections = list(script.sections)
    placeholder_titles = [s.title for s in sections if _PLACEHOLDER_TITLE.match(s.title.strip())]

    narration_parts = [script.hook, script.introduction]
    narration_parts.extend(s.content for s in sections)
    narration_parts.extend([script.conclusion, script.call_to_action])
    narration = "\n".join(part for part in narration_parts if part)

    normalized_sentences = [
        _norm_sentence(sentence)
        for sentence in _sentences(narration)
        if len(_norm_sentence(sentence).split()) >= 8
    ]
    sentence_counts = Counter(normalized_sentences)
    repeated_sentences = [
        sentence for sentence, count in sentence_counts.items() if count >= 2
    ]

    section_tokens = [(section.title, _tokens(section.content)) for section in sections]
    similar_pairs: list[dict[str, object]] = []
    for (title_a, a), (title_b, b) in combinations(section_tokens, 2):
        if not a or not b:
            continue
        similarity = len(a & b) / max(1, len(a | b))
        if similarity >= 0.50:
            similar_pairs.append(
                {"a": title_a, "b": title_b, "similarity": round(similarity, 3)}
            )

    broken_hyphens = _BROKEN_HYPHEN.findall(narration)

    # Repeated sentence openings are a useful signal for rescue-model boilerplate,
    # even when a single noun changes later in the sentence.
    starters: list[str] = []
    for sentence in normalized_sentences:
        words = sentence.split()
        if len(words) >= 8:
            starters.append(" ".join(words[:7]))
    starter_counts = Counter(starters)
    repeated_starters = [starter for starter, count in starter_counts.items() if count >= 3]

    issues: list[str] = []
    if placeholder_titles:
        issues.append("placeholder section titles: " + ", ".join(placeholder_titles[:4]))
    if repeated_sentences:
        issues.append(f"repeated long sentences: {len(repeated_sentences)}")
    if repeated_starters:
        issues.append(f"repeated boilerplate sentence openings: {len(repeated_starters)}")
    if similar_pairs:
        issues.append(f"near-duplicate sections: {len(similar_pairs)}")
    if broken_hyphens:
        issues.append(f"broken hyphen/apostrophe tokens: {len(broken_hyphens)}")

    penalty = (
        min(30, len(placeholder_titles) * 18)
        + min(28, len(repeated_sentences) * 8)
        + min(18, len(repeated_starters) * 6)
        + min(24, len(similar_pairs) * 8)
        + min(10, len(broken_hyphens) * 4)
    )
    score = max(0.0, round(100.0 - penalty, 1))
    passed = (
        score >= 82.0
        and not placeholder_titles
        and len(repeated_sentences) <= 1
        and len(repeated_starters) == 0
        and len(similar_pairs) <= 1
        and not broken_hyphens
    )
    return {
        "passed": passed,
        "score": score,
        "placeholder_titles": placeholder_titles,
        "repeated_sentences": repeated_sentences[:8],
        "repeated_starters": repeated_starters[:8],
        "similar_pairs": similar_pairs[:8],
        "broken_hyphens": broken_hyphens[:8],
        "issues": issues,
    }
