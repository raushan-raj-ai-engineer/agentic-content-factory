from __future__ import annotations

import asyncio
import gc
import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from piper import PiperVoice

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
    ) -> None:
        self._legacy_model_path = Path(model_path)
        self._legacy_config_path = Path(config_path)
        self._voice_root = Path(voice_root)
        self._voice_root.mkdir(parents=True, exist_ok=True)

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

        if not self._piper_models and not self._system_voices:
            raise FileNotFoundError(
                "No local TTS voice found. Install a Piper voice or a macOS "
                "system voice before generating narration."
            )

        self._narrator_assignment: dict[str, tuple[str, str, int | None]] = {}
        self._character_assignment: dict[
            tuple[str, str],
            tuple[str, str, int | None],
        ] = {}

        print(
            f"[VOICE] Discovered {len(self._piper_models)} Piper model(s), "
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
            duration = self._get_duration_seconds(
                output
            )
            print(
                f"[CACHE] Voice HIT: "
                f"{profile.locale}/{profile.style}"
            )
            cache_hit = True

        elif backend == "piper":
            duration = await self._generate_piper(
                spoken_text,
                output_path,
                resolved,
            )
            shutil.copy2(
                output,
                cache_path,
            )
            cache_hit = False
        elif backend == "macos":
            duration = await self._generate_macos(
                spoken_text,
                output_path,
                resolved,
            )
            shutil.copy2(
                output,
                cache_path,
            )
            cache_hit = False

        elif not cache_path.is_file():
            raise RuntimeError(
                f"Unsupported voice backend: {backend}"
            )

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
            "cache_hit": cache_hit,
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
        piper = self._matching_piper(locale)

        if piper:
            model = piper[0]
            speaker_id = (
                model.speaker_ids[0]
                if model.speaker_ids
                else None
            )
            return (
                "piper",
                model.key,
                speaker_id,
            )

        system = self._matching_system(locale)

        if system:
            return (
                "macos",
                system[0].name,
                None,
            )

        self._raise_missing_language(locale)

    def _pick_character(
        self,
        locale: str,
        character: str,
    ) -> tuple[str, str, int | None]:
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
        gc.collect()

        print(
            f"[RESOURCE] Released {count} loaded Piper voice model(s)."
        )

    def _cache_key(
        self,
        text: str,
        profile: VoiceProfile,
    ) -> str:
        model_fingerprint = ""

        if profile.backend == "piper":
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
            "v": 1,
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
