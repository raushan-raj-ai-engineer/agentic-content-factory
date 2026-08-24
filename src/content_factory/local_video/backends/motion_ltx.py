from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import time

from ..config import EngineConfig
from ..hardware import detect_hardware


class LTXMotionBackend:
    def __init__(self, cfg: EngineConfig, *, force: bool = False):
        self.cfg = cfg
        self.force = force

    def validate(self) -> None:
        hw = detect_hardware()
        if (hw.platform == "Darwin" and hw.machine == "arm64" and hw.total_memory_gb is not None and hw.total_memory_gb <= 8.5 and not self.force):
            raise RuntimeError("Local LTX motion is blocked on Apple Silicon 8GB by default. Use a stronger self-owned motion worker; --force is available only for deliberate experiments.")
        if not self.cfg.ltx_repo.exists():
            raise RuntimeError(f"LTX-Video repo missing: {self.cfg.ltx_repo}. Run bootstrap with --motion")
        if not self.cfg.ltx_python.exists():
            raise RuntimeError(f"LTX Python venv missing: {self.cfg.ltx_python}. Run bootstrap with --motion")
        if not (self.cfg.ltx_repo / "inference.py").exists():
            raise RuntimeError("LTX inference.py not found")

    @staticmethod
    def frames_for(seconds: float, fps: int) -> int:
        raw = max(9, int(round(seconds * fps)))
        # LTX pads to N*8+1; choose that shape explicitly.
        return max(9, ((raw - 1 + 7) // 8) * 8 + 1)

    def generate(self, image: Path, prompt: str, out: Path, *, seconds: float, fps: int, width: int, height: int, seed: int) -> Path:
        self.validate()
        out.parent.mkdir(parents=True, exist_ok=True)
        if seconds > 5.0 and not self.force:
            raise RuntimeError("Shot longer than 5 seconds blocked for local diffusion. Split dialogue into shorter shots or pass --force.")
        frames = self.frames_for(seconds, fps)
        temp_dir = out.parent / (out.stem + "_ltx")
        temp_dir.mkdir(parents=True, exist_ok=True)
        before = set(temp_dir.rglob("*.mp4"))
        cmd = [
            str(self.cfg.ltx_python), "inference.py",
            "--prompt", prompt,
            "--conditioning_media_paths", str(image.resolve()),
            "--conditioning_start_frames", "0",
            "--height", str(height), "--width", str(width),
            "--num_frames", str(frames), "--frame_rate", str(fps),
            "--seed", str(seed),
            "--pipeline_config", self.cfg.ltx_pipeline_config,
            "--output_path", str(temp_dir.resolve()),
        ]
        env = os.environ.copy()
        env.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
        print("[MOTION LTX]", " ".join(cmd))
        subprocess.run(cmd, cwd=str(self.cfg.ltx_repo), env=env, check=True)
        candidates = sorted(set(temp_dir.rglob("*.mp4")) - before, key=lambda p: p.stat().st_mtime)
        if not candidates:
            candidates = sorted(temp_dir.rglob("*.mp4"), key=lambda p: p.stat().st_mtime)
        if not candidates:
            raise RuntimeError(f"LTX returned without an mp4 in {temp_dir}")
        shutil.copy2(candidates[-1], out)
        return out
