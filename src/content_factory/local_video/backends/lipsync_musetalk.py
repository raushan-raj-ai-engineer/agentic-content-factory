from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess

from ..config import EngineConfig


class MuseTalkBackend:
    """Optional local lip-sync adapter. Auto-enabled only on CUDA."""

    def __init__(self, cfg: EngineConfig):
        self.cfg = cfg

    def available(self) -> bool:
        return (self.cfg.musetalk_repo / "scripts" / "inference.py").exists() and self.cfg.musetalk_python.exists()

    def sync(self, video: Path, audio: Path, out: Path) -> Path:
        if not self.available():
            raise RuntimeError("MuseTalk not installed. Run bootstrap with --lipsync on a CUDA machine.")
        work = out.parent / (out.stem + "_musetalk")
        work.mkdir(parents=True, exist_ok=True)
        cfg_path = work / "task.yaml"
        result_dir = work / "results"
        task = {
            "job": {
                "video_path": str(video.resolve()),
                "audio_path": str(audio.resolve()),
                "result_name": out.name,
            }
        }
        # Minimal YAML writer keeps V19 core dependency-free.
        def q(v: str) -> str:
            return '"' + str(v).replace('\\', '\\\\').replace('"', '\\"') + '"'
        cfg_path.write_text(
            "job:\n"
            f"  video_path: {q(task['job']['video_path'])}\n"
            f"  audio_path: {q(task['job']['audio_path'])}\n"
            f"  result_name: {q(task['job']['result_name'])}\n",
            encoding="utf-8",
        )
        cmd = [
            str(self.cfg.musetalk_python), "-m", "scripts.inference",
            "--inference_config", str(cfg_path),
            "--result_dir", str(result_dir),
            "--version", "v15",
            "--output_vid_name", out.name,
        ]
        env = os.environ.copy()
        print("[LIPSYNC MUSETALK]", " ".join(cmd))
        subprocess.run(cmd, cwd=str(self.cfg.musetalk_repo), env=env, check=True)
        candidates = sorted(result_dir.rglob(out.name), key=lambda p: p.stat().st_mtime)
        if not candidates:
            candidates = sorted(result_dir.rglob("*.mp4"), key=lambda p: p.stat().st_mtime)
        if not candidates:
            raise RuntimeError("MuseTalk completed without an mp4")
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidates[-1], out)
        return out
