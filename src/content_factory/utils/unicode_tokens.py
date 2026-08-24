from __future__ import annotations

import unicodedata


TOKEN_PUNCT = {
    "+",
    "#",
    ".",
    "-",
    "_",
}


def unicode_tokens(
    text: str,
    *,
    min_length: int = 1,
) -> list[str]:
    """
    Multilingual tokenizer that keeps Indic combining marks attached to
    their visible word.

    Python's stdlib regex \\w can split a single visible Indic-script word
    into multiple pieces because combining marks are separate Unicode code
    points. This tokenizer groups letters/numbers/marks into one token.
    """
    value = unicodedata.normalize(
        "NFKC",
        text or "",
    ).lower()

    chars: list[str] = []

    for char in value:
        category = unicodedata.category(
            char
        )

        if (
            char.isalnum()
            or category.startswith("M")
            or char in TOKEN_PUNCT
        ):
            chars.append(char)
        else:
            chars.append(" ")

    result: list[str] = []

    for token in "".join(chars).split():
        cleaned = token.strip("._-")

        if not cleaned:
            continue

        if len(cleaned) < min_length:
            continue

        result.append(cleaned)

    return result


def unicode_token_set(
    text: str,
    *,
    min_length: int = 1,
) -> set[str]:
    return set(
        unicode_tokens(
            text,
            min_length=min_length,
        )
    )
