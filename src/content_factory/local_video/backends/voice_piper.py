from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from ..config import EngineConfig


VOICE_REPO = "https://huggingface.co/rhasspy/piper-voices/resolve/main/hi/hi_IN"
VOICE_PATHS = {
    "hi_IN-pratham-medium": "pratham/medium/hi_IN-pratham-medium",
    "hi_IN-priyamvada-medium": "priyamvada/medium/hi_IN-priyamvada-medium",
    "hi_IN-rohan-medium": "rohan/medium/hi_IN-rohan-medium",
}


class PiperVoiceBackend:
    def __init__(self, cfg: EngineConfig):
        self.cfg = cfg

    def voice_name(self, character_id: str) -> str:
        return self.cfg.piper_voice_map.get(character_id, self.cfg.piper_voice_map["default"])

    def _paths(self, voice: str) -> tuple[Path, Path]:
        return self.cfg.piper_voice_dir / f"{voice}.onnx", self.cfg.piper_voice_dir / f"{voice}.onnx.json"

    def ensure_voice(self, voice: str) -> tuple[Path, Path]:
        if voice not in VOICE_PATHS:
            raise RuntimeError(f"Unsupported packaged Piper Hindi voice: {voice}")
        model, config = self._paths(voice)
        if model.exists() and config.exists():
            return model, config
        curl = shutil.which("curl")
        if not curl:
            raise RuntimeError("curl is required to download Piper voices")
        self.cfg.piper_voice_dir.mkdir(parents=True, exist_ok=True)
        base = f"{VOICE_REPO}/{VOICE_PATHS[voice]}"
        subprocess.run([curl, "-L", "--fail", f"{base}.onnx", "-o", str(model)], check=True)
        subprocess.run([curl, "-L", "--fail", f"{base}.onnx.json", "-o", str(config)], check=True)
        return model, config

    def synthesize(self, text: str, character_id: str, out_wav: Path) -> Path:
        piper = shutil.which("piper")
        if not piper:
            raise RuntimeError("piper executable not found. Run: bash scripts/bootstrap_local_video_engine.sh --voice")
        voice = self.voice_name(character_id)
        model, _ = self.ensure_voice(voice)
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [piper, "--model", str(model), "--output_file", str(out_wav)],
            input=text + "\n", text=True, check=True,
        )
        return out_wav
