"""Optional local ASR timing; never claim text estimates are forced alignment."""

from __future__ import annotations

import json
import math
import os
import re
import wave
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path


def tokens(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text.casefold(), re.UNICODE)


def wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as audio:
        return audio.getnframes() / audio.getframerate()


@lru_cache(maxsize=1)
def _model(name: str):
    from faster_whisper import WhisperModel

    return WhisperModel(name, device="cpu", compute_type="int8")


def create_timing(path: Path, text: str, locale: str = "") -> dict:
    duration = wav_seconds(path)
    mode = os.getenv("STUDY_WORD_TIMING", "off").lower()
    if mode not in {"off", "auto", "required"}:
        raise ValueError("STUDY_WORD_TIMING must be off, auto or required")
    payload = {
        "version": 1,
        "duration_seconds": duration,
        "source": "text_estimate",
        "words": [],
        "coverage": 0.0,
    }
    if mode != "off":
        try:
            segments, _ = _model(os.getenv("STUDY_WHISPER_MODEL", "base")).transcribe(
                str(path),
                language=locale.replace("-", "_").split("_")[0] or None,
                word_timestamps=True,
                vad_filter=False,
                condition_on_previous_text=False,
            )
            words = []
            last = 0.0
            for segment in segments:
                for word in segment.words or []:
                    start, end = float(word.start), float(word.end)
                    if not (math.isfinite(start) and math.isfinite(end)):
                        continue
                    start = max(last, min(duration, start))
                    end = max(start, min(duration, end))
                    if end > start and tokens(word.word):
                        words.append(
                            {"word": word.word.strip(), "start": start, "end": end}
                        )
                        last = end
            expected = tokens(text)
            heard = tokens(" ".join(w["word"] for w in words))
            matched = sum(
                b.size
                for b in SequenceMatcher(
                    None, expected, heard, autojunk=False
                ).get_matching_blocks()
            )
            coverage = matched / max(1, len(expected))
            if coverage < 0.75 or not words:
                raise ValueError(f"ASR script coverage {coverage:.0%} is below 75%")
            payload.update(
                source="asr_word_timestamps", words=words, coverage=round(coverage, 4)
            )
        except Exception as exc:
            if mode == "required":
                raise RuntimeError(
                    "Required word timing failed; check alignment extra/model"
                ) from exc
            payload["warning"] = (
                f"Word timing unavailable: {type(exc).__name__}; using estimates"
            )
    path.with_suffix(".timing.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    return payload


def schedule_beats(
    beats: list[dict], narration: str, timing: dict, duration: float
) -> dict:
    """Match cue tokens in order to actual words; report unmatched estimates."""
    words = (
        timing.get("words", []) if timing.get("source") == "asr_word_timestamps" else []
    )
    spoken, starts = [], []
    for word in words:
        for token in tokens(word["word"]):
            spoken.append(token)
            starts.append(float(word["start"]))
    estimated = tokens(narration)
    cursor = estimate_cursor = 0
    last = 0.0
    result = []
    for index, beat in enumerate(beats):
        cue = tokens(str(beat.get("cue", "")))
        hit = next(
            (
                i
                for i in range(cursor, len(spoken) - len(cue) + 1)
                if cue and spoken[i : i + len(cue)] == cue
            ),
            None,
        )
        source = "asr_word_timestamps" if hit is not None else "text_estimate"
        if hit is not None:
            start = starts[hit]
            cursor = hit + len(cue)
        else:
            pos = next(
                (
                    i
                    for i in range(estimate_cursor, len(estimated) - len(cue) + 1)
                    if cue and estimated[i : i + len(cue)] == cue
                ),
                None,
            )
            start = duration * (
                pos / max(1, len(estimated))
                if pos is not None
                else index / max(1, len(beats))
            )
            if pos is not None:
                estimate_cursor = pos + len(cue)
        start = max(last, min(max(0.0, duration - 0.1), start))
        result.append(
            {"start": round(start, 4), "source": source, "cue": beat.get("cue", "")}
        )
        last = start
    return {
        "beats": result,
        "measured_ratio": sum(b["source"] == "asr_word_timestamps" for b in result)
        / max(1, len(result)),
    }
