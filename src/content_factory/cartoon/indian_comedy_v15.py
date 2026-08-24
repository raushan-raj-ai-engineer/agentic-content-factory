from __future__ import annotations

import json
import os
import time
import urllib.request
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

_CACHE_HOURS = 12
_TREND_URLS = (
    "https://trends.google.com/trends/trendingsearches/daily/rss?geo=IN",
    "https://trends.google.co.in/trends/trendingsearches/daily/rss?geo=IN",
)

_SAFE_THEME_RULES = (
    ("sports-match fever", ("cricket", "football", "league", "match", "ipl", "premier league", "world cup")),
    ("school / exam / holiday confusion", ("school", "holiday", "exam", "result", "college", "admission")),
    ("new phone / gadget obsession", ("phone", "mobile", "buds", "earbud", "laptop", "gadget", "launch", "ai")),
    ("flight / airport / travel chaos", ("flight", "airline", "airport", "indigo", "travel")),
    ("train / commute confusion", ("train", "railway", "metro", "station")),
    ("online shopping / sale temptation", ("sale", "shopping", "amazon", "flipkart", "price", "deal")),
    ("weather / monsoon family chaos", ("rain", "monsoon", "heat", "weather", "storm")),
    ("movie / show / music buzz", ("movie", "film", "trailer", "song", "show", "series")),
)

_UNSAFE_OR_LOW_VALUE = (
    "election", "minister", "prime minister", "chief minister", "bjp", "congress", "party",
    "murder", "rape", "death", "dead", "killed", "accident", "war", "terror", "attack",
    "arrest", "court", "scam", "suicide", "disease", "outbreak", "earthquake", "flood deaths",
)

_DEFAULT_THEMES = [
    "sports-match fever",
    "school / exam / holiday confusion",
    "new phone / gadget obsession",
    "flight / airport / travel chaos",
    "online shopping / sale temptation",
    "weather / monsoon family chaos",
    "AI assistant misunderstandings",
    "UPI / digital-payment family confusion",
]

_PERSONALITY_BLOCK = """
RECURRING CHARACTER PERSONALITIES (keep them recognizable across episodes):
- guddu: quick-witted lead; notices absurdity; underplays the best one-liners instead of shouting.
- bittu: confident but often wrong; turns a small misunderstanding into a bigger problem.
- babuji: old-school authority with literal logic; can accidentally become the joke; do not make him angry every scene.
- mai: calm practical observer; strongest deadpan reality-check when useful.
- chacha: opportunistic gossip / self-declared expert; often joins the wrong side with confidence.
- teacher: straight-faced authority; dry reactions land better than constant scolding.
- shopkeeper/lala: transactional cleverness; sees a business angle in everything.
Do not force every episode to use all of them. Keep relationships and personality logic consistent.
""".strip()

_DIRECTOR_BLOCK = """
INDIAN COMEDY DIRECTOR V15 — ENGAGEMENT GRAMMAR:
- Open on the conflict, surprise, embarrassment or misunderstanding within the first 5-8 seconds. No slow exposition.
- Write ORIGINAL jokes only. Never copy a known meme caption, comedian punchline, movie dialogue, reel joke or creator script.
- Use a ladder: normal setup -> small turn -> reaction -> stronger misunderstanding -> interruption/callback -> payoff.
- Not every line is a punchline. Short setup lines make the punchline land harder.
- Aim for a meaningful comic turn/reaction roughly every 15-30 seconds, with a stronger escalation every 45-90 seconds.
- Use interruptions, overheard lines, self-owns, literal misunderstandings, status reversals and callbacks.
- Dialogue should feel spoken, not written: short clauses, incomplete reactions, character-specific vocabulary, no lecture paragraphs.
- For Hindi/Magahi/Bhojpuri/Hinglish, preserve natural rhythm and code-switching; do not mechanically translate English joke structures.
- Keep visual comedy tied to the spoken beat: stare, pause, prop reveal, wrong entrance, group reaction, failed attempt, silent beat.
- Final scene must pay off something introduced earlier; prefer a callback or reversal over a moral speech.
- Keep it family-safe and monetization-friendly: avoid slurs, sexual jokes, graphic harm, dangerous imitation, humiliating protected groups, and real-person impersonation.
- Trend context is inspiration for relatable situations only; never claim a trend is factual news inside the story unless the user explicitly asks for current-event content.
""".strip()
_V16_STORY_DIRECTOR_BLOCK = """
STORY & PERFORMANCE DIRECTOR V16 — ENTERTAINMENT-FIRST RULES:
- Every scene must have a character WANT, an OBSTACLE, an ATTEMPT and a CONSEQUENCE. If nothing changes, the scene is filler: rewrite it.
- Build comedy through cause-and-effect, not disconnected jokes: setup -> misunderstanding/attempt -> reaction -> escalation -> reversal -> callback/payoff.
- Rotate joke mechanisms: literal misunderstanding, confident mistake, status reversal, interruption, visual contradiction, self-own, deadpan reaction, callback. Do not use the same mechanism repeatedly.
- Never explain a punchline after it lands. Let the reaction/cut carry the beat.
- Two-person conversation: short alternating turns, clear reply target, reaction beats, and occasional interruption. Avoid long monologues unless the story specifically requires a speech.
- Group conversation: only the active speaker and one meaningful listener/reactor matter at a time. Do not make everyone talk or move continuously.
- SCHOOL / STAGE / ASSEMBLY / KAVI-SAMMELAN / CROWD SPEECH: identify one focal speaker addressing the group. After 1-3 short speech lines, cut to one selective audience reaction or interruption, then return to the speaker for a comeback. Use crowd reaction as payoff, not constant noise.
- For speeches, write the speaker to scan/address the group, not the camera. Direct-to-camera is allowed only when the premise explicitly needs viewers/narration.
- Audio-first writing: use short spoken clauses, commas, dashes and brief interjections where a natural pause/reaction should happen. Avoid paragraph-length dialogue.
- Visual actions must be motivated by the story beat: point at the person/object being discussed, turn toward an interrupter, hold on a stare after a punchline, reveal the prop when it becomes relevant.
- Hook in 5-8 seconds, meaningful comic turn every ~15-30 seconds, stronger escalation every ~45-90 seconds, final callback/reversal that pays off an earlier setup.
- Make the episode feel more entertaining than a string of jokes: preserve tension, curiosity and character relationships between punchlines.
""".strip()



def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def _cache_path() -> Path:
    return _root() / "configs" / "hindi_mass_trends_live.json"


def _fallback_path() -> Path:
    return _root() / "configs" / "hindi_mass_trends.json"


def _map_titles_to_themes(titles: list[str]) -> list[str]:
    themes: list[str] = []
    for raw in titles:
        text = " ".join(str(raw).lower().split())
        if not text or any(bad in text for bad in _UNSAFE_OR_LOW_VALUE):
            continue
        for theme, keywords in _SAFE_THEME_RULES:
            if any(k in text for k in keywords) and theme not in themes:
                themes.append(theme)
                break
        if len(themes) >= 6:
            break
    return themes


def _fetch_trend_titles(timeout: float = 2.5) -> list[str]:
    headers = {"User-Agent": "Mozilla/5.0 ContentFactoryV15/1.0"}
    last_error: Exception | None = None
    for url in _TREND_URLS:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload = response.read()
            root = ET.fromstring(payload)
            titles = []
            for item in root.findall(".//item"):
                title = item.findtext("title")
                if title:
                    titles.append(title.strip())
            if titles:
                return titles
        except Exception as exc:  # network is optional
            last_error = exc
    if last_error:
        raise last_error
    return []


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_cache(themes: list[str]) -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": "15.0",
        "updated_epoch": int(time.time()),
        "source": "Google Trends India RSS (safe themes only)",
        "themes": themes,
    }
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _fallback_themes() -> list[str]:
    payload = _read_json(_fallback_path())
    themes = [str(x) for x in payload.get("safe_theme_seeds", []) if str(x).strip()]
    return themes or list(_DEFAULT_THEMES)


@lru_cache(maxsize=1)
def current_safe_trend_themes() -> tuple[str, ...]:
    mode = os.getenv("CONTENT_FACTORY_HINDI_TRENDS", "auto").strip().lower()
    cache = _read_json(_cache_path())
    updated = int(cache.get("updated_epoch", 0) or 0)
    cached_themes = [str(x) for x in cache.get("themes", []) if str(x).strip()]
    fresh = bool(cached_themes) and (time.time() - updated) < (_CACHE_HOURS * 3600)

    if fresh:
        themes = cached_themes
        source = "cache"
    elif mode not in {"off", "0", "false", "disabled"}:
        try:
            titles = _fetch_trend_titles()
            themes = _map_titles_to_themes(titles)
            if themes:
                _write_cache(themes)
                source = "live-safe-themes"
            else:
                themes = cached_themes or _fallback_themes()
                source = "fallback"
        except Exception:
            themes = cached_themes or _fallback_themes()
            source = "offline-fallback"
    else:
        themes = cached_themes or _fallback_themes()
        source = "refresh-off"

    themes = list(dict.fromkeys(themes))[:6]
    print(f"[INDIAN COMEDY V15] trend_source={source}; safe_themes={','.join(themes)}")
    return tuple(themes)


def indian_comedy_prompt_block(language_code: str) -> str:
    themes = current_safe_trend_themes()
    trend_line = ", ".join(themes) if themes else "relatable everyday Indian life"
    return (
        _DIRECTOR_BLOCK
        + "\n\n"
        + _V16_STORY_DIRECTOR_BLOCK
        + "\n\n"
        + _PERSONALITY_BLOCK
        + "\n\nCURRENT SAFE TREND THEMES (OPTIONAL inspiration, never copied jokes): "
        + trend_line
        + ". Use a trend only when it naturally fits the user's premise; otherwise ignore it."
    )


def reset_trend_cache_for_tests() -> None:
    current_safe_trend_themes.cache_clear()
