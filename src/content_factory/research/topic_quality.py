from __future__ import annotations

import itertools
import re
from collections import Counter

from content_factory.utils.unicode_tokens import unicode_tokens


MONTH_WORDS = {
    # English
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
    # Spanish / Portuguese
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    "janeiro", "fevereiro", "março", "marco", "maio", "junho",
    "julho", "setembro", "outubro", "dezembro",
    # French
    "janvier", "février", "fevrier", "mars", "avril", "mai", "juin",
    "juillet", "août", "aout", "septembre", "octobre", "novembre", "décembre",
    "decembre",
    # Indonesian
    "januari", "februari", "maret", "mei", "juni", "juli",
    "agustus", "oktober", "desember",
    # Hindi
    "जनवरी", "फरवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई",
    "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर",
    # Arabic
    "يناير", "فبراير", "مارس", "أبريل", "ابريل", "مايو", "يونيو",
    "يوليو", "أغسطس", "اغسطس", "سبتمبر", "أكتوبر", "اكتوبر", "نوفمبر", "ديسمبر",
    # Urdu
    "جنوری", "فروری", "مارچ", "اپریل", "مئی", "جون", "جولائی",
    "اگست", "ستمبر", "اکتوبر", "نومبر", "دسمبر",
    # Bengali
    "জানুয়ারি", "ফেব্রুয়ারি", "মার্চ", "এপ্রিল", "মে", "জুন",
    "জুলাই", "আগস্ট", "সেপ্টেম্বর", "অক্টোবর", "নভেম্বর", "ডিসেম্বর",
}

DATE_CONNECTORS = {
    "de", "del", "do", "da", "di", "le", "el", "the", "of",
    "on", "em", "en", "du", "des", "d", "วันที่",
}

WEEKDAY_WORDS = {
    # EN
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    # ES/PT
    "lunes", "martes", "miércoles", "miercoles", "jueves", "viernes",
    "sábado", "sabado", "domingo",
    "segunda", "terça", "terca", "quarta", "quinta", "sexta", "sábado", "sabado",
    # FR
    "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche",
    # ID
    "senin", "selasa", "rabu", "kamis", "jumat", "jum'at", "sabtu", "minggu",
    # HI
    "सोमवार", "मंगलवार", "बुधवार", "गुरुवार", "शुक्रवार", "शनिवार", "रविवार",
    # AR
    "الاثنين", "الثلاثاء", "الأربعاء", "الاربعاء", "الخميس", "الجمعة", "السبت", "الأحد", "الاحد",
}

SEMANTIC_STOP_WORDS = {
    # Media / recency
    "news", "noticias", "notícia", "noticia", "nouvelles", "live", "vivo",
    "ao", "en", "radio", "rádio", "today", "hoy", "hoje", "daily",
    "matinal", "resumen", "resumo", "informativo", "edition", "edição", "edicao",
    "viernes", "sexta", "current", "latest", "agora",
    # Generic grammar
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "from",
    "with", "de", "del", "do", "da", "em", "e", "la", "el", "los", "las",
    "un", "uma", "um", "para", "por", "que", "com",
}

_JAPANESE_DATE_RE = re.compile(
    r"(?:20\d{2}\s*年\s*)?\d{1,2}\s*月\s*\d{1,2}\s*日"
)

_NUMERIC_DATE_RE = re.compile(
    r"(?<!\d)(?:\d{1,2}[./-]){1,2}\d{1,4}(?!\d)"
)


def is_calendar_only_topic(
    text: str,
) -> bool:
    """
    True only when the topic is essentially a calendar/date label.

    Examples rejected:
      21 De Agosto
      August 21
      21 August 2026
      21/08/2026
      2026年8月21日

    Examples kept:
      Eclipse Lunar De Agosto De 2026
      August 21 earthquake
      21 August cricket final
    """
    value = (
        text
        or ""
    ).strip()

    if not value:
        return False

    if _JAPANESE_DATE_RE.fullmatch(
        re.sub(r"\s+", "", value)
    ):
        return True

    if _NUMERIC_DATE_RE.fullmatch(
        value
    ):
        return True

    tokens = unicode_tokens(
        value,
        min_length=1,
    )

    if not tokens:
        return False

    has_month = any(
        token in MONTH_WORDS
        for token in tokens
    )

    has_day_number = any(
        token.isdigit()
        and 1 <= int(token) <= 31
        for token in tokens
    )

    if not (
        has_month
        and has_day_number
    ):
        return False

    semantic = []

    for token in tokens:
        if token in MONTH_WORDS:
            continue

        if token in DATE_CONNECTORS:
            continue

        if token in WEEKDAY_WORDS:
            continue

        if token.isdigit():
            # Day or year.
            continue

        semantic.append(
            token
        )

    return len(
        semantic
    ) == 0


def evidence_semantic_coherence(
    topic: str,
    titles: list[str],
) -> float:
    """
    Estimate whether exact-string matching points to ONE subject.

    A date phrase can appear in unrelated prayer/news/sports/radio uploads.
    Lexical relevance is high, but semantic coherence is low.

    Returns 0..1.
    """
    clean_titles = [
        item.strip()
        for item in titles
        if str(
            item
            or ""
        ).strip()
    ]

    if len(
        clean_titles
    ) < 2:
        return 1.0 if clean_titles else 0.0

    topic_tokens = set(
        unicode_tokens(
            topic,
            min_length=2,
        )
    )

    semantic_sets: list[
        set[str]
    ] = []

    for title in clean_titles:
        values = set(
            unicode_tokens(
                title,
                min_length=2,
            )
        )

        filtered = {
            token
            for token in values
            if token not in topic_tokens
            and token not in MONTH_WORDS
            and token not in DATE_CONNECTORS
            and token not in WEEKDAY_WORDS
            and token not in SEMANTIC_STOP_WORDS
            and not token.isdigit()
        }

        if filtered:
            semantic_sets.append(
                filtered
            )

    if len(
        semantic_sets
    ) < 2:
        return 0.0

    document_frequency = Counter()

    for values in semantic_sets:
        for token in values:
            document_frequency[
                token
            ] += 1

    top_share = (
        max(
            document_frequency.values(),
            default=0,
        )
        / len(
            semantic_sets
        )
    )

    pair_values = []

    for left, right in itertools.combinations(
        semantic_sets,
        2,
    ):
        union = left | right

        if not union:
            continue

        pair_values.append(
            len(
                left & right
            )
            / len(
                union
            )
        )

    pairwise = (
        sum(
            pair_values
        )
        / len(
            pair_values
        )
        if pair_values
        else 0.0
    )

    return max(
        0.0,
        min(
            1.0,
            top_share
            * 0.70
            + pairwise
            * 0.30,
        ),
    )


def topic_quality_factor(
    topic: str,
    titles: list[str],
) -> tuple[float, float]:
    """
    Bounded penalty; never boosts.

    Calendar-only topics are rejected very strongly.
    One-word / low-context topics need coherent evidence to avoid a false win.
    """
    coherence = evidence_semantic_coherence(
        topic,
        titles,
    )

    if is_calendar_only_topic(
        topic
    ):
        return (
            0.15,
            coherence,
        )

    token_count = len(
        unicode_tokens(
            topic,
            min_length=2,
        )
    )

    if (
        token_count <= 1
        and coherence < 0.22
    ):
        return (
            0.65,
            coherence,
        )

    if (
        token_count <= 2
        and coherence < 0.12
    ):
        return (
            0.82,
            coherence,
        )

    return (
        1.0,
        coherence,
    )
