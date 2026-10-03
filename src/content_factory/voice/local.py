from __future__ import annotations

import asyncio
import gc
import math
import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
import tempfile
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from kokoro_onnx import Kokoro
except ImportError:
    Kokoro = None  # optional high-quality local voice backend

try:
    import soundfile as sf
except ImportError:
    sf = None  # type: ignore[assignment]

try:
    from piper import PiperVoice
except ImportError:
    PiperVoice = None  # optional voice extra

try:
    from piper import SynthesisConfig  # modern piper1-gpl / piper-tts
except ImportError:  # compatibility with older Piper package
    SynthesisConfig = None  # type: ignore[assignment]

from content_factory.voice.base import VoiceProvider
from content_factory.voice.director import VoiceDirector, VoiceProfile


@dataclass(frozen=True)
class PiperModelInfo:
    key: str
    model_path: Path
    config_path: Path
    locale: str
    language_family: str
    num_speakers: int
    speaker_ids: tuple[int, ...]


@dataclass(frozen=True)
class SystemVoiceInfo:
    name: str
    locale: str


class LocalVoiceProvider(VoiceProvider):
    """
    Multilingual local voice bank.

    Priority:
      1. Piper voice matching script locale
      2. macOS locally installed system voice matching locale
      3. hard error for known non-English locale instead of speaking it badly

    Narrator remains stable; explicit characters get alternate stable speakers.
    """

    def __init__(
        self,
        model_path: str = "models/piper/en_US-lessac-medium.onnx",
        config_path: str = "models/piper/en_US-lessac-medium.onnx.json",
        voice_root: str = "models/piper",
        language: str | None = None,
        voice_profile: str = "auto",
        preferred_voice: str | None = None,
        preferred_backend: str = "auto",
    ) -> None:
        self._legacy_model_path = Path(model_path)
        self._legacy_config_path = Path(config_path)
        self._voice_root = Path(voice_root)
        self._voice_root.mkdir(parents=True, exist_ok=True)
        self._voice_profile = (voice_profile or "auto").strip().lower()
        self._preferred_voice = (preferred_voice or "").strip()
        self._preferred_backend = (preferred_backend or "auto").strip().lower()
        self._kokoro_model_path = Path(
            os.getenv(
                "KOKORO_MODEL_PATH",
                "models/kokoro/kokoro-v1.0.fp16.onnx",
            )
        )
        self._kokoro_voices_path = Path(
            os.getenv(
                "KOKORO_VOICES_PATH",
                "models/kokoro/voices-v1.0.bin",
            )
        )
        self._kokoro_voice_male = os.getenv(
            "KOKORO_VOICE_US_MALE", "am_michael"
        ).strip() or "am_michael"
        self._kokoro_voice_female = os.getenv(
            "KOKORO_VOICE_US_FEMALE", "af_bella"
        ).strip() or "af_bella"
        self._kokoro_available = bool(
            Kokoro is not None
            and sf is not None
            and self._kokoro_model_path.is_file()
            and self._kokoro_voices_path.is_file()
        )
        self._kokoro: Any | None = None

        self._cache_root = Path(
            os.getenv(
                "CONTENT_FACTORY_VOICE_CACHE",
                ".cache/content_factory/voice",
            )
        )
        self._cache_root.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._director = VoiceDirector(
            language_override=(
                language
                or os.getenv("CONTENT_FACTORY_LANGUAGE", "auto")
            )
        )

        self._piper_models = self._discover_piper_models()
        self._system_voices = self._discover_system_voices()
        self._loaded_voices: dict[Path, PiperVoice] = {}

        # Preserve old behavior if only the original Lessac model exists.
        if (
            self._legacy_model_path.exists()
            and self._legacy_config_path.exists()
            and all(
                item.model_path != self._legacy_model_path
                for item in self._piper_models
            )
        ):
            legacy = self._model_info(
                self._legacy_model_path,
                self._legacy_config_path,
            )
            if legacy:
                self._piper_models.append(legacy)

        if not self._kokoro_available and not self._piper_models and not self._system_voices:
            raise FileNotFoundError(
                "No local TTS voice found. Install Kokoro/Piper or a macOS "
                "system voice before generating narration."
            )

        self._narrator_assignment: dict[str, tuple[str, str, int | None]] = {}
        self._character_assignment: dict[
            tuple[str, str],
            tuple[str, str, int | None],
        ] = {}

        print(
            f"[VOICE] Kokoro={'ready' if self._kokoro_available else 'not-installed'}, "
            f"{len(self._piper_models)} Piper model(s), "
            f"{len(self._system_voices)} macOS voice(s)."
        )

    async def generate(
        self,
        text: str,
        output_path: str,
    ) -> int:
        """Backward-compatible default generation."""
        result = await self.generate_for_segment(
            text=text,
            output_path=output_path,
            segment_index=1,
            total_segments=1,
            audience="",
            topic="",
        )
        return int(result["duration_seconds"])

    async def generate_for_segment(
        self,
        *,
        text: str,
        output_path: str,
        segment_index: int,
        total_segments: int,
        audience: str,
        topic: str,
    ) -> dict[str, Any]:
        if not text.strip():
            raise ValueError("Voice text cannot be empty.")

        profile = self._director.profile_for(
            text=text,
            audience=audience,
            topic=topic,
            segment_index=segment_index,
            total_segments=total_segments,
        )

        character, spoken_text = self._director.extract_character(text)

        assignment = self._assignment_for(
            locale=profile.locale,
            character=character,
        )

        backend, voice_key, speaker_id = assignment

        resolved = VoiceProfile(
            locale=profile.locale,
            role=profile.role,
            style=profile.style,
            character=character,
            voice_key=voice_key,
            speaker_id=speaker_id,
            backend=backend,
            length_scale=profile.length_scale,
            noise_scale=profile.noise_scale,
            noise_w_scale=profile.noise_w_scale,
            rate_wpm=profile.rate_wpm,
        )

        cache_key = self._cache_key(
            spoken_text,
            resolved,
        )
        cache_path = (
            self._cache_root
            / f"{cache_key}.wav"
        )
        output = Path(output_path)

        if cache_path.is_file():
            output.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            shutil.copy2(
                cache_path,
                output,
            )
            print(
                f"[CACHE] Voice HIT: "
                f"{profile.locale}/{profile.style}"
            )
            cache_hit = True

        elif backend == "kokoro":
            await self._generate_kokoro(
                spoken_text,
                output_path,
                resolved,
            )
            cache_hit = False
        elif backend == "piper":
            await self._generate_piper(
                spoken_text,
                output_path,
                resolved,
            )
            cache_hit = False
        elif backend == "macos":
            await self._generate_macos(
                spoken_text,
                output_path,
                resolved,
            )
            cache_hit = False

        elif not cache_path.is_file():
            raise RuntimeError(
                f"Unsupported voice backend: {backend}"
            )

        pace = await self._normalize_voice_pace(
            text=spoken_text,
            path=output,
            target_wpm=resolved.rate_wpm,
            allow_rewrite=not cache_hit,
        )
        duration = self._get_duration_seconds(output)

        if not cache_hit:
            shutil.copy2(output, cache_path)

        return {
            "duration_seconds": duration,
            "locale": resolved.locale,
            "role": resolved.role,
            "style": resolved.style,
            "character": resolved.character,
            "voice": resolved.voice_key,
            "speaker_id": resolved.speaker_id,
            "backend": resolved.backend,
            "length_scale": resolved.length_scale,
            "rate_wpm": resolved.rate_wpm,
            "effective_wpm": pace["effective_wpm"],
            "active_wpm": pace.get("active_wpm"),
            "silence_seconds": pace.get("silence_seconds"),
            "silence_ratio": pace.get("silence_ratio"),
            "pace_adjusted": pace["adjusted"],
            "cache_hit": cache_hit,
            "voice_profile": self._voice_profile,
            "preferred_voice": self._preferred_voice or None,
        }

    @staticmethod
    def _spoken_word_count(text: str) -> int:
        return max(1, len(re.findall(r"\b[\w@./+-]+\b", text, flags=re.UNICODE)))

    @classmethod
    def _effective_wpm(cls, text: str, path: Path) -> float:
        with wave.open(str(path), "rb") as wav_file:
            frame_count = wav_file.getnframes()
            frame_rate = wav_file.getframerate()
        seconds = frame_count / max(1, frame_rate)
        return cls._spoken_word_count(text) / max(0.1, seconds) * 60.0

    @staticmethod
    def _pace_tempo(measured_wpm: float, target_wpm: int) -> float:
        """Return a conservative pitch-preserving tempo correction.

        Study narration should be calm, not sluggish. A small dead-band avoids
        reprocessing already-natural speech; caps protect narrator identity.
        """
        if measured_wpm <= 0:
            return 1.0
        low = target_wpm * 0.96
        high = target_wpm * 1.05
        if low <= measured_wpm <= high:
            return 1.0
        desired = target_wpm / measured_wpm
        try:
            max_tempo = float(os.getenv("CONTENT_FACTORY_VOICE_MAX_TEMPO", "1.12"))
        except ValueError:
            max_tempo = 1.12
        try:
            min_tempo = float(os.getenv("CONTENT_FACTORY_VOICE_MIN_TEMPO", "0.90"))
        except ValueError:
            min_tempo = 0.90
        max_tempo = max(1.0, min(1.15, max_tempo))
        min_tempo = max(0.86, min(1.0, min_tempo))
        if measured_wpm < low:
            return min(max_tempo, max(1.0, desired))
        return max(min_tempo, min(1.0, desired))

    @staticmethod
    def _audio_activity_stats(path: Path) -> dict[str, float]:
        """Estimate voiced/activity time from a mono/stereo PCM16 WAV.

        The result is diagnostic, not a speech recognizer. A short hangover
        window keeps consonants and natural micro-pauses inside active speech
        while still exposing long synthetic silences between sentences.
        """
        try:
            with wave.open(str(path), "rb") as wav_file:
                channels = max(1, wav_file.getnchannels())
                sample_width = wav_file.getsampwidth()
                frame_rate = max(1, wav_file.getframerate())
                frame_count = wav_file.getnframes()
                raw = wav_file.readframes(frame_count)
            total_seconds = frame_count / frame_rate
            if sample_width != 2 or not raw:
                return {"total_seconds": total_seconds, "active_seconds": total_seconds, "silence_seconds": 0.0, "silence_ratio": 0.0}
            samples = array("h")
            samples.frombytes(raw)
            window_frames = max(1, int(frame_rate * 0.02))
            window_samples = window_frames * channels
            flags: list[bool] = []
            # ~-43.5 dBFS RMS. Kokoro/Piper silence is normally far below this.
            threshold = 220.0
            for start in range(0, len(samples), window_samples):
                chunk = samples[start : start + window_samples]
                if not chunk:
                    continue
                rms = math.sqrt(sum(int(v) * int(v) for v in chunk) / len(chunk))
                flags.append(rms >= threshold)
            if not flags:
                return {"total_seconds": total_seconds, "active_seconds": total_seconds, "silence_seconds": 0.0, "silence_ratio": 0.0}
            # Expand speech activity by 80 ms on each side.
            expanded = flags[:]
            radius = 4
            for i, active in enumerate(flags):
                if not active:
                    continue
                for j in range(max(0, i - radius), min(len(flags), i + radius + 1)):
                    expanded[j] = True
            active_seconds = min(total_seconds, sum(expanded) * 0.02)
            silence_seconds = max(0.0, total_seconds - active_seconds)
            return {
                "total_seconds": total_seconds,
                "active_seconds": active_seconds,
                "silence_seconds": silence_seconds,
                "silence_ratio": silence_seconds / max(0.001, total_seconds),
            }
        except Exception:
            return {"total_seconds": 0.0, "active_seconds": 0.0, "silence_seconds": 0.0, "silence_ratio": 0.0}

    async def _compact_study_pauses(self, path: Path) -> bool:
        """Cap only abnormally long TTS pauses while keeping natural phrasing."""
        if not shutil.which("ffmpeg"):
            return False
        temp = path.with_suffix(path.suffix + ".pauses.wav")
        # Internal silence must exceed 0.90s before it is shortened; retain
        # 0.45s so equations, code and conceptual transitions can still breathe.
        filter_expr = (
            "silenceremove="
            "start_periods=1:start_duration=0.05:start_threshold=-45dB:"
            "stop_periods=-1:stop_duration=0.90:stop_threshold=-45dB:stop_silence=0.45"
        )
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(path),
            "-filter:a", filter_expr,
            "-ar", "22050", "-ac", "1", "-c:a", "pcm_s16le",
            str(temp),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode == 0 and temp.is_file() and temp.stat().st_size > 1024:
            before = self._get_duration_seconds(path)
            after = self._get_duration_seconds(temp)
            # Do not accept pathological trimming.
            if after >= max(1, int(before * 0.72)) and after <= before:
                temp.replace(path)
                return after < before
        temp.unlink(missing_ok=True)
        if process.returncode != 0:
            print(
                "[VOICE PAUSE] ffmpeg pause normalization skipped: "
                + stderr.decode("utf-8", errors="replace")[:180]
            )
        return False

    async def _normalize_voice_pace(
        self,
        *,
        text: str,
        path: Path,
        target_wpm: int,
        allow_rewrite: bool,
    ) -> dict[str, object]:
        """Normalize local narration into a natural study-speed band.

        v0.5.4 only slowed fast voices. Kokoro exposed the opposite failure mode:
        some segments landed near 108-120 WPM with excessive synthetic pauses.
        v0.5.5 first caps long pauses, then adjusts *either* direction with
        ffmpeg atempo, which preserves pitch.
        """
        raw_wpm = self._effective_wpm(text, path)
        raw_activity = self._audio_activity_stats(path)
        pause_adjusted = False
        tempo_adjusted = False

        if allow_rewrite and target_wpm <= 165:
            pause_adjusted = await self._compact_study_pauses(path)

        compacted_wpm = self._effective_wpm(text, path)
        tempo = self._pace_tempo(compacted_wpm, target_wpm)
        if allow_rewrite and abs(tempo - 1.0) >= 0.015 and shutil.which("ffmpeg"):
            temp = path.with_suffix(path.suffix + ".paced.wav")
            process = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-loglevel", "error",
                "-i", str(path),
                "-filter:a", f"atempo={tempo:.5f}",
                "-ar", "22050", "-ac", "1", "-c:a", "pcm_s16le",
                str(temp),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()
            if process.returncode == 0 and temp.is_file():
                temp.replace(path)
                tempo_adjusted = True
            else:
                temp.unlink(missing_ok=True)
                print(
                    "[VOICE PACE] ffmpeg pace normalization skipped: "
                    + stderr.decode("utf-8", errors="replace")[:180]
                )

        effective = self._effective_wpm(text, path)
        activity = self._audio_activity_stats(path)
        active_wpm = (
            self._spoken_word_count(text) / max(0.1, activity["active_seconds"]) * 60.0
            if activity["active_seconds"] > 0 else effective
        )
        adjusted = pause_adjusted or tempo_adjusted
        print(
            "[VOICE PACE] "
            f"target≈{target_wpm}wpm raw={raw_wpm:.1f}wpm "
            f"compacted={compacted_wpm:.1f}wpm final={effective:.1f}wpm "
            f"active≈{active_wpm:.1f}wpm silence={activity['silence_ratio']*100:.1f}% "
            f"tempo={tempo:.3f} adjusted={'YES' if adjusted else 'NO'}"
        )
        return {
            "effective_wpm": round(effective, 1),
            "active_wpm": round(active_wpm, 1),
            "silence_seconds": round(activity["silence_seconds"], 2),
            "silence_ratio": round(activity["silence_ratio"], 4),
            "raw_silence_ratio": round(raw_activity["silence_ratio"], 4),
            "adjusted": adjusted,
            "pause_adjusted": pause_adjusted,
            "tempo_adjusted": tempo_adjusted,
        }

    def _assignment_for(
        self,
        *,
        locale: str,
        character: str | None,
    ) -> tuple[str, str, int | None]:
        if character is None:
            if locale in self._narrator_assignment:
                return self._narrator_assignment[locale]

            assignment = self._pick_narrator(locale)
            self._narrator_assignment[locale] = assignment
            return assignment

        key = (locale, character.lower())

        if key in self._character_assignment:
            return self._character_assignment[key]

        assignment = self._pick_character(
            locale,
            character,
        )
        self._character_assignment[key] = assignment
        return assignment

    def _pick_narrator(
        self,
        locale: str,
    ) -> tuple[str, str, int | None]:
        # An exact user choice always wins when installed. This is useful for
        # creators who audition voices and want repeatable identity.
        exact = self._find_exact_voice(self._preferred_voice)
        if exact is not None:
            return exact

        piper = self._matching_piper(locale)
        system = self._matching_system(locale)

        profile_preferences = self._profile_preferences(
            self._voice_profile,
            locale,
        )

        if (
            locale.lower() == "en_us"
            and getattr(self, "_kokoro_available", False)
            and getattr(self, "_preferred_backend", "auto") in {"auto", "kokoro"}
        ):
            key = (
                self._kokoro_voice_female
                if self._voice_profile == "us-female-clear"
                else self._kokoro_voice_male
            )
            return ("kokoro", key, None)

        if getattr(self, "_preferred_backend", "auto") == "kokoro" and not getattr(self, "_kokoro_available", False):
            raise RuntimeError(
                "Kokoro voice backend requested but model assets are missing. "
                "Run: bash scripts/setup_kokoro_voice.sh"
            )

        for key in profile_preferences["piper"]:
            if getattr(self, "_preferred_backend", "auto") not in {"auto", "piper"}:
                break
            match = next(
                (item for item in piper if item.key.lower() == key.lower()),
                None,
            )
            if match is not None:
                speaker_id = match.speaker_ids[0] if match.speaker_ids else None
                return ("piper", match.key, speaker_id)

        for name in profile_preferences["macos"]:
            if getattr(self, "_preferred_backend", "auto") not in {"auto", "macos"}:
                break
            match = next(
                (item for item in system if item.name.lower() == name.lower()),
                None,
            )
            if match is not None:
                return ("macos", match.name, None)

        if piper and getattr(self, "_preferred_backend", "auto") in {"auto", "piper"}:
            model = piper[0]
            speaker_id = model.speaker_ids[0] if model.speaker_ids else None
            return ("piper", model.key, speaker_id)

        if system and getattr(self, "_preferred_backend", "auto") in {"auto", "macos"}:
            return ("macos", system[0].name, None)

        self._raise_missing_language(locale)

    def _find_exact_voice(
        self,
        value: str,
    ) -> tuple[str, str, int | None] | None:
        requested = (value or "").strip().lower()
        if not requested:
            return None

        if getattr(self, "_kokoro_available", False) and requested in {
            getattr(self, "_kokoro_voice_male", "am_michael").lower(),
            getattr(self, "_kokoro_voice_female", "af_bella").lower(),
            "am_michael", "am_fenrir", "am_puck", "af_bella", "af_nicole",
            "af_sarah", "af_aoede", "af_kore", "af_nova",
        }:
            return ("kokoro", value, None)

        for item in self._piper_models:
            if item.key.lower() == requested:
                speaker_id = item.speaker_ids[0] if item.speaker_ids else None
                return ("piper", item.key, speaker_id)

        for item in self._system_voices:
            if item.name.lower() == requested:
                return ("macos", item.name, None)

        available = []
        if getattr(self, "_kokoro_available", False):
            available.extend([
                getattr(self, "_kokoro_voice_male", "am_michael"),
                getattr(self, "_kokoro_voice_female", "af_bella"),
            ])
        available.extend(item.key for item in self._piper_models)
        available.extend(item.name for item in self._system_voices)
        preview = ", ".join(available[:12])
        raise RuntimeError(
            f"Requested voice {value!r} is not installed. "
            f"Run 'bash run_topic.sh --list-voices' to inspect local voices. "
            f"Available examples: {preview or 'none'}"
        )

    @staticmethod
    def _profile_preferences(
        profile: str,
        locale: str,
    ) -> dict[str, tuple[str, ...]]:
        # Profiles are preferences, not impersonations. The default U.S. male
        # profile intentionally favors Piper Ryan, a local American-English
        # narrator suitable for clear technical lessons.
        if locale.lower() != "en_us":
            return {"piper": (), "macos": ()}

        if profile == "us-male-warm":
            return {
                "piper": (
                    "en_US-libritts-high",
                    "en_US-ryan-medium",
                    "en_US-ryan-high",
                    "en_US-joe-medium",
                    "en_US-john-medium",
                ),
                "macos": (
                    "Alex",
                    "Eddy",
                    "Reed",
                    "Rocko",
                    "Fred",
                ),
            }

        if profile == "us-female-clear":
            return {
                "piper": (
                    "en_US-lessac-medium",
                    "en_US-amy-medium",
                    "en_US-kathleen-low",
                ),
                "macos": (
                    "Samantha",
                    "Ava",
                    "Allison",
                    "Susan",
                ),
            }

        return {"piper": (), "macos": ()}

    def _pick_character(
        self,
        locale: str,
        character: str,
    ) -> tuple[str, str, int | None]:
        # Keep character inserts inside the same premium voice family as the
        # narrator. Falling straight from Kokoro narration to a macOS system
        # voice is perceptually jarring in educational videos.
        if (
            locale.lower() == "en_us"
            and getattr(self, "_kokoro_available", False)
            and getattr(self, "_preferred_backend", "auto") in {"auto", "kokoro"}
        ):
            raw = os.getenv(
                "KOKORO_CHARACTER_VOICES",
                "am_fenrir,am_puck,af_bella,af_nicole",
            )
            options = [v.strip() for v in raw.split(",") if v.strip()]
            narrator = self._narrator_assignment.get(locale)
            narrator_voice = narrator[1].lower() if narrator and narrator[0] == "kokoro" else ""
            options = [v for v in options if v.lower() != narrator_voice]
            if options:
                slot = self._director.character_slot(character, len(options))
                return ("kokoro", options[slot], None)

        piper = self._matching_piper(locale)

        # Prefer a multi-speaker Piper model for character consistency.
        multi = [
            item
            for item in piper
            if len(item.speaker_ids) > 1
        ]

        if multi:
            model = multi[0]
            slots = list(model.speaker_ids)

            # Avoid narrator speaker 0 when possible.
            if len(slots) > 1:
                slots = slots[1:]

            slot = self._director.character_slot(
                character,
                len(slots),
            )

            return (
                "piper",
                model.key,
                slots[slot],
            )

        # Different Piper models can represent different characters.
        if len(piper) > 1:
            slot = self._director.character_slot(
                character,
                len(piper) - 1,
            ) + 1

            model = piper[slot]

            return (
                "piper",
                model.key,
                (
                    model.speaker_ids[0]
                    if model.speaker_ids
                    else None
                ),
            )

        system = self._matching_system(locale)

        # If narrator is Piper, all matching macOS voices are available
        # as character voices. If narrator is macOS, avoid its first voice.
        if system:
            offset = 0
            narrator = self._narrator_assignment.get(locale)
            if (
                narrator
                and narrator[0] == "macos"
                and len(system) > 1
            ):
                system = system[1:]

            slot = self._director.character_slot(
                character,
                len(system),
            )

            return (
                "macos",
                system[slot].name,
                None,
            )

        # Only one Piper voice exists: keep identity but vary delivery.
        if piper:
            model = piper[0]
            return (
                "piper",
                model.key,
                (
                    model.speaker_ids[0]
                    if model.speaker_ids
                    else None
                ),
            )

        self._raise_missing_language(locale)

    async def _generate_kokoro(
        self,
        text: str,
        output_path: str,
        profile: VoiceProfile,
    ) -> int:
        if not self._kokoro_available or Kokoro is None or sf is None:
            raise RuntimeError(
                "Kokoro is not ready. Run: bash scripts/setup_kokoro_voice.sh"
            )
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        def synthesize() -> None:
            if self._kokoro is None:
                self._kokoro = Kokoro(
                    str(self._kokoro_model_path),
                    str(self._kokoro_voices_path),
                )
            samples, sample_rate = self._kokoro.create(
                text,
                voice=profile.voice_key or self._kokoro_voice_male,
                speed=1.0,
                lang="en-us",
            )
            sf.write(str(path), samples, sample_rate, subtype="PCM_16")

        await asyncio.to_thread(synthesize)
        print(
            f"[VOICE] locale={profile.locale} role={profile.role} "
            f"style={profile.style} backend=kokoro "
            f"voice={profile.voice_key}"
        )
        return self._get_duration_seconds(path)

    async def _generate_piper(
        self,
        text: str,
        output_path: str,
        profile: VoiceProfile,
    ) -> int:
        info = next(
            item
            for item in self._piper_models
            if item.key == profile.voice_key
        )

        voice = self._loaded_voices.get(
            info.model_path
        )

        if voice is None:
            if PiperVoice is None:
                raise RuntimeError("Install the voice extra: pip install -e '.[voice]'")
            voice = PiperVoice.load(
                info.model_path,
                config_path=info.config_path,
            )
            self._loaded_voices[
                info.model_path
            ] = voice

        path = Path(output_path)
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with wave.open(
            str(path),
            "wb",
        ) as wav_file:
            if SynthesisConfig is not None:
                syn_config = SynthesisConfig(
                    speaker_id=profile.speaker_id,
                    length_scale=profile.length_scale,
                    noise_scale=profile.noise_scale,
                    noise_w_scale=profile.noise_w_scale,
                )

                try:
                    voice.synthesize_wav(
                        text,
                        wav_file,
                        syn_config=syn_config,
                    )
                except TypeError:
                    self._synthesize_old_piper(
                        voice=voice,
                        text=text,
                        wav_file=wav_file,
                        profile=profile,
                    )
            else:
                self._synthesize_old_piper(
                    voice=voice,
                    text=text,
                    wav_file=wav_file,
                    profile=profile,
                )

        print(
            f"[VOICE] locale={profile.locale} "
            f"role={profile.role} "
            f"style={profile.style} "
            f"backend=piper "
            f"voice={profile.voice_key} "
            f"speaker={profile.speaker_id if profile.speaker_id is not None else '-'}"
        )

        return self._get_duration_seconds(path)

    @staticmethod
    def _synthesize_old_piper(
        *,
        voice: PiperVoice,
        text: str,
        wav_file: wave.Wave_write,
        profile: VoiceProfile,
    ) -> None:
        # Old rhasspy/piper uses synthesize(... speaker_id, length_scale ...).
        synthesize = getattr(
            voice,
            "synthesize",
            None,
        )

        if synthesize is None:
            voice.synthesize_wav(
                text,
                wav_file,
            )
            return

        kwargs = {
            "speaker_id": profile.speaker_id,
            "length_scale": profile.length_scale,
            "noise_scale": profile.noise_scale,
            "noise_w": profile.noise_w_scale,
        }

        try:
            synthesize(
                text,
                wav_file,
                **kwargs,
            )
        except TypeError:
            voice.synthesize_wav(
                text,
                wav_file,
            )

    async def _generate_macos(
        self,
        text: str,
        output_path: str,
        profile: VoiceProfile,
    ) -> int:
        if shutil.which("say") is None:
            raise RuntimeError(
                "macOS 'say' command is unavailable."
            )

        if shutil.which("ffmpeg") is None:
            raise RuntimeError(
                "ffmpeg is required to convert macOS speech to WAV."
            )

        path = Path(output_path)
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            aiff_path = (
                Path(temp_dir)
                / "speech.aiff"
            )

            process = await asyncio.create_subprocess_exec(
                "say",
                "-v",
                str(profile.voice_key),
                "-r",
                str(profile.rate_wpm),
                "-o",
                str(aiff_path),
                text,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            _, stderr = await process.communicate()

            if process.returncode != 0:
                raise RuntimeError(
                    "macOS say failed: "
                    + stderr.decode(
                        "utf-8",
                        errors="replace",
                    )
                )

            convert = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-y",
                "-i",
                str(aiff_path),
                "-ar",
                "22050",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            _, convert_stderr = await convert.communicate()

            if convert.returncode != 0:
                raise RuntimeError(
                    "ffmpeg voice conversion failed: "
                    + convert_stderr.decode(
                        "utf-8",
                        errors="replace",
                    )
                )

        print(
            f"[VOICE] locale={profile.locale} "
            f"role={profile.role} "
            f"style={profile.style} "
            f"backend=macos "
            f"voice={profile.voice_key}"
        )

        return self._get_duration_seconds(path)

    def _discover_piper_models(
        self,
    ) -> list[PiperModelInfo]:
        candidates: set[Path] = set()

        if self._voice_root.exists():
            candidates.update(
                self._voice_root.rglob("*.onnx")
            )

        # Backward-compatible direct model path.
        if self._legacy_model_path.exists():
            candidates.add(
                self._legacy_model_path
            )

        result: list[PiperModelInfo] = []

        for model_path in sorted(candidates):
            config_path = Path(
                str(model_path) + ".json"
            )

            if not config_path.exists():
                continue

            info = self._model_info(
                model_path,
                config_path,
            )

            if info:
                result.append(info)

        # Multi-speaker models first because they are best for character work.
        result.sort(
            key=lambda item: (
                item.locale,
                -item.num_speakers,
                item.key,
            )
        )

        return result

    @staticmethod
    def _model_info(
        model_path: Path,
        config_path: Path,
    ) -> PiperModelInfo | None:
        try:
            data = json.loads(
                config_path.read_text(
                    encoding="utf-8"
                )
            )
        except Exception:
            return None

        language = data.get("language") or {}
        locale = str(
            language.get("code")
            or ""
        ).strip()

        if not locale:
            # Fallback from file name like en_US-lessac-medium.onnx
            match = re.match(
                r"^([a-z]{2}_[A-Z]{2})-",
                model_path.name,
            )
            locale = (
                match.group(1)
                if match
                else "en_US"
            )

        family = locale.split("_", 1)[0]

        speaker_map = data.get(
            "speaker_id_map"
        ) or {}

        num_speakers = int(
            data.get("num_speakers")
            or max(
                1,
                len(speaker_map),
            )
        )

        if speaker_map:
            speaker_ids = tuple(
                sorted(
                    {
                        int(value)
                        for value in speaker_map.values()
                    }
                )
            )
        else:
            speaker_ids = tuple(
                range(num_speakers)
            )

        return PiperModelInfo(
            key=model_path.stem,
            model_path=model_path,
            config_path=config_path,
            locale=locale,
            language_family=family,
            num_speakers=max(1, num_speakers),
            speaker_ids=speaker_ids,
        )

    @staticmethod
    def _discover_system_voices(
    ) -> list[SystemVoiceInfo]:
        if shutil.which("say") is None:
            return []

        try:
            completed = subprocess.run(
                ["say", "-v", "?"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except Exception:
            return []

        result: list[SystemVoiceInfo] = []

        for line in completed.stdout.splitlines():
            # Typical:
            # Samantha             en_US    # Hello...
            match = re.match(
                r"^(.+?)\s{2,}([a-z]{2}_[A-Z]{2})\s+#",
                line,
            )

            if not match:
                continue

            result.append(
                SystemVoiceInfo(
                    name=match.group(1).strip(),
                    locale=match.group(2).strip(),
                )
            )

        return result

    def _matching_piper(
        self,
        locale: str,
    ) -> list[PiperModelInfo]:
        exact = [
            item
            for item in self._piper_models
            if item.locale.lower() == locale.lower()
        ]

        if exact:
            return exact

        family = locale.split("_", 1)[0].lower()

        return [
            item
            for item in self._piper_models
            if item.language_family.lower() == family
        ]

    def _matching_system(
        self,
        locale: str,
    ) -> list[SystemVoiceInfo]:
        exact = [
            item
            for item in self._system_voices
            if item.locale.lower() == locale.lower()
        ]

        if exact:
            return exact

        family = locale.split("_", 1)[0].lower()

        return [
            item
            for item in self._system_voices
            if item.locale.lower().startswith(
                family + "_"
            )
        ]

    @staticmethod
    def _raise_missing_language(
        locale: str,
    ) -> None:
        raise RuntimeError(
            f"No local voice is installed for {locale}. "
            "Install a matching Piper voice under models/piper or add a "
            "matching macOS voice in System Settings > Accessibility > "
            "Read & Speak. The pipeline stops instead of using the wrong "
            "language/accent."
        )

    @staticmethod
    def _get_duration_seconds(
        audio_path: Path,
    ) -> int:
        with wave.open(
            str(audio_path),
            "rb",
        ) as wav_file:
            frame_count = wav_file.getnframes()
            frame_rate = wav_file.getframerate()

        if frame_rate <= 0:
            raise ValueError(
                f"Invalid WAV sample rate: {audio_path}"
            )

        return max(
            1,
            round(frame_count / frame_rate),
        )

    def release(self) -> None:
        """Release loaded Piper models before diffusion starts."""
        count = len(
            self._loaded_voices
        )
        self._loaded_voices.clear()
        had_kokoro = self._kokoro is not None
        self._kokoro = None
        gc.collect()

        print(
            f"[RESOURCE] Released {count} loaded Piper voice model(s)"
            + (" + Kokoro." if had_kokoro else ".")
        )

    def _cache_key(
        self,
        text: str,
        profile: VoiceProfile,
    ) -> str:
        model_fingerprint = ""

        if profile.backend == "kokoro":
            try:
                model_stat = self._kokoro_model_path.stat()
                voices_stat = self._kokoro_voices_path.stat()
                model_fingerprint = (
                    f"{self._kokoro_model_path.resolve()}|{model_stat.st_size}|"
                    f"{model_stat.st_mtime_ns}|{voices_stat.st_size}|"
                    f"{voices_stat.st_mtime_ns}"
                )
            except Exception:
                model_fingerprint = str(self._kokoro_model_path)
        elif profile.backend == "piper":
            for item in self._piper_models:
                if item.key == profile.voice_key:
                    try:
                        stat = item.model_path.stat()
                        model_fingerprint = (
                            f"{item.model_path.resolve()}|"
                            f"{stat.st_size}|{stat.st_mtime_ns}"
                        )
                    except Exception:
                        model_fingerprint = str(
                            item.model_path
                        )
                    break

        payload = {
            "v": 4,
            "text": text,
            "locale": profile.locale,
            "role": profile.role,
            "style": profile.style,
            "character": profile.character,
            "voice": profile.voice_key,
            "speaker_id": profile.speaker_id,
            "backend": profile.backend,
            "length_scale": profile.length_scale,
            "noise_scale": profile.noise_scale,
            "noise_w_scale": profile.noise_w_scale,
            "rate_wpm": profile.rate_wpm,
            "model_fingerprint": model_fingerprint,
            "voice_profile": self._voice_profile,
            "preferred_voice": self._preferred_voice,
            "preferred_backend": self._preferred_backend,
        }

        return hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                ensure_ascii=False,
            ).encode(
                "utf-8"
            )
        ).hexdigest()

    def inventory(
        self,
    ) -> dict[str, Any]:
        return {
            "selected_profile": self._voice_profile,
            "selected_backend": self._preferred_backend,
            "kokoro": (
                [
                    {"key": self._kokoro_voice_male, "locale": "en_US", "default": True},
                    {"key": self._kokoro_voice_female, "locale": "en_US", "default": False},
                ]
                if self._kokoro_available
                else []
            ),
            "preferred_voice": self._preferred_voice,
            "preferred_backend": self._preferred_backend,
            "piper": [
                {
                    "key": item.key,
                    "locale": item.locale,
                    "speakers": item.num_speakers,
                    "path": str(item.model_path),
                }
                for item in self._piper_models
            ],
            "macos": [
                {
                    "name": item.name,
                    "locale": item.locale,
                }
                for item in self._system_voices
            ],
        }
