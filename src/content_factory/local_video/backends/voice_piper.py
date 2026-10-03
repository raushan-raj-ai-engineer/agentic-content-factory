from __future__ import annotations
import hashlib
import json
import os
import shutil
import tempfile
import wave
from pathlib import Path
from ..config import EngineConfig


class PiperVoiceBackend:
    def __init__(self, cfg: EngineConfig):
        self.cfg = cfg
        self._voices = {}

    def voice_name(self, character_id: str) -> str:
        return self.cfg.piper_voice_map.get(character_id, self.cfg.piper_voice_map["default"])

    def _paths(self, voice: str) -> tuple[Path, Path]:
        if Path(voice).name != voice or voice in ("", ".", ".."):
            raise ValueError("Voice must be a model name, not a path")
        return self.cfg.piper_voice_dir / f"{voice}.onnx", self.cfg.piper_voice_dir / f"{voice}.onnx.json"

    def ensure_voice(self, voice: str) -> tuple[Path, Path]:
        model, config = self._paths(voice)
        if not model.is_file() or not config.is_file():
            raise RuntimeError(f"Piper voice {voice} missing in {self.cfg.piper_voice_dir}. "
                               "Use bash scripts/download_voice.sh " + voice)
        if model.stat().st_size < 1024:
            raise RuntimeError(f"Incomplete Piper model: {model}")
        json.loads(config.read_text(encoding="utf-8"))
        return model, config

    @staticmethod
    def _valid_wav(path: Path) -> bool:
        try:
            with wave.open(str(path), "rb") as wav:
                return wav.getnframes() > 0 and wav.getframerate() > 0
        except (OSError, EOFError, wave.Error):
            return False

    def synthesize(self, text: str, character_id: str, out_wav: Path) -> Path:
        if not text.strip():
            raise ValueError("Cannot synthesize empty narration")
        try:
            import onnxruntime
            onnxruntime.disable_telemetry_events()
        except ImportError:
            # Piper itself will report a clear dependency error when real ONNX
            # inference is attempted. Keeping this optional makes cache/tests portable.
            pass
        from piper import PiperVoice
        model, config = self.ensure_voice(self.voice_name(character_id))
        signature = f"{model.resolve()}:{model.stat().st_size}:{model.stat().st_mtime_ns}:{config.read_text()}:piper-default-v1:{text}"
        key = hashlib.sha256(signature.encode()).hexdigest()
        cache = self.cfg.cache_root / "voice"
        cache.mkdir(parents=True, exist_ok=True)
        cached = cache / f"{key}.wav"
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        if self._valid_wav(cached):
            shutil.copy2(cached, out_wav)
            return out_wav
        if model not in self._voices:
            self._voices[model] = PiperVoice.load(str(model), config_path=str(config))
        fd, name = tempfile.mkstemp(suffix=".wav", dir=cache)
        os.close(fd)
        temporary = Path(name)
        try:
            with wave.open(str(temporary), "wb") as wav:
                self._voices[model].synthesize_wav(text, wav)
            if not self._valid_wav(temporary):
                raise RuntimeError("Piper produced invalid audio")
            temporary.replace(cached)
            shutil.copy2(cached, out_wav)
        finally:
            temporary.unlink(missing_ok=True)
        return out_wav
