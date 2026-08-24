from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DiscoverySignal:
    topic: str
    score: float
    raw_topic: str | None = None
    clarity_score: float = 100.0
    google_trends_rank: int | None = None
    google_trends_traffic: int = 0
    google_news_matches: int = 0
    hacker_news_matches: int = 0
    related_headlines: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    language_code: str = "en"
    language_name: str = "English"
    market_geo: str = ""
    market_name: str = ""
    language_priority: float = 0.50
    language_priority_rank: int = 999
    youtube_market_reach_m: float = 0.0
    market_mentions: int = 1


_SIGNALS: dict[str, DiscoverySignal] = {}


def clear_signals() -> None:
    _SIGNALS.clear()


def set_signal(signal: DiscoverySignal) -> None:
    _SIGNALS[signal.topic.strip().lower()] = signal


def get_signal(topic: str) -> DiscoverySignal | None:
    return _SIGNALS.get(topic.strip().lower())
