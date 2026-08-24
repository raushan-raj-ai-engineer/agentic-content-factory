from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


@dataclass(frozen=True)
class EngineConfig:
    project_root: Path
    engine_root: Path
    models_root: Path
    cache_root: Path
    ltx_repo: Path
    ltx_python: Path
    ltx_pipeline_config: str
    animatediff_python: Path
    svd_python: Path
    svd_model: str
    svd_frames: int
    svd_steps: int
    svd_motion_bucket: int
    svd_noise_aug: float
    svd_conditioning_fps: int
    svd_export_fps: float
    animatediff_repo: str
    animatediff_checkpoint: str
    animatediff_base_model: str
    animatediff_frames: int
    animatediff_steps: int
    animatediff_strength: float
    piper_voice_dir: Path
    piper_voice_map: dict[str, str]
    musetalk_repo: Path
    musetalk_python: Path
    default_motion_backend: str
    default_voice_backend: str
    default_lipsync_backend: str
    width: int
    height: int
    fps: int
    max_shot_seconds: float

    @classmethod
    def from_project(cls, project_root: Path) -> "EngineConfig":
        project_root = project_root.resolve()
        engine_root = Path(_env("CONTENT_FACTORY_VIDEO_ENGINE_HOME", str(project_root / ".local-video-engine"))).expanduser()
        models_root = Path(_env("CONTENT_FACTORY_VIDEO_MODELS", str(engine_root / "models"))).expanduser()
        cache_root = Path(_env("CONTENT_FACTORY_VIDEO_CACHE", str(engine_root / "cache"))).expanduser()
        svd_default = engine_root / "venvs" / "svd" / "bin" / "python"
        legacy_diffusion_python = engine_root / "venvs" / "animatediff" / "bin" / "python"
        if not svd_default.exists() and legacy_diffusion_python.exists():
            svd_default = legacy_diffusion_python
        return cls(
            project_root=project_root,
            engine_root=engine_root,
            models_root=models_root,
            cache_root=cache_root,
            ltx_repo=Path(_env("LTX_VIDEO_REPO", str(engine_root / "LTX-Video"))).expanduser(),
            ltx_python=Path(_env("LTX_VIDEO_PYTHON", str(engine_root / "venvs" / "ltx" / "bin" / "python"))).expanduser(),
            ltx_pipeline_config=_env("LTX_VIDEO_PIPELINE_CONFIG", "configs/ltxv-2b-0.9.8-distilled.yaml"),
            animatediff_python=Path(_env("ANIMATEDIFF_PYTHON", str(engine_root / "venvs" / "animatediff" / "bin" / "python"))).expanduser(),
            svd_python=Path(_env("SVD_PYTHON", str(svd_default))).expanduser(),
            svd_model=_env("SVD_MODEL", "stabilityai/stable-video-diffusion-img2vid"),
            svd_frames=int(_env("SVD_FRAMES", "10")),
            svd_steps=int(_env("SVD_STEPS", "20")),
            svd_motion_bucket=int(_env("SVD_MOTION_BUCKET", "100")),
            svd_noise_aug=float(_env("SVD_NOISE_AUG", "0.02")),
            svd_conditioning_fps=int(_env("SVD_CONDITIONING_FPS", "6")),
            svd_export_fps=float(_env("SVD_EXPORT_FPS", "3.0")),
            animatediff_repo=_env("ANIMATEDIFF_REPO", "ByteDance/AnimateDiff-Lightning"),
            animatediff_checkpoint=_env("ANIMATEDIFF_CHECKPOINT", "animatediff_lightning_4step_diffusers.safetensors"),
            animatediff_base_model=_env("ANIMATEDIFF_BASE_MODEL", "stable-diffusion-v1-5/stable-diffusion-v1-5"),
            animatediff_frames=int(_env("ANIMATEDIFF_FRAMES", "8")),
            animatediff_steps=int(_env("ANIMATEDIFF_STEPS", "4")),
            animatediff_strength=float(_env("ANIMATEDIFF_STRENGTH", "0.42")),
            piper_voice_dir=Path(_env("PIPER_VOICE_DIR", str(models_root / "piper"))).expanduser(),
            piper_voice_map={
                "babuji": _env("PIPER_VOICE_BABUJI", "hi_IN-rohan-medium"),
                "guddu": _env("PIPER_VOICE_GUDDU", "hi_IN-pratham-medium"),
                "bittu": _env("PIPER_VOICE_BITTU", "hi_IN-rohan-medium"),
                "mai": _env("PIPER_VOICE_MAI", "hi_IN-priyamvada-medium"),
                "default": _env("PIPER_VOICE_DEFAULT", "hi_IN-pratham-medium"),
            },
            musetalk_repo=Path(_env("MUSETALK_REPO", str(engine_root / "MuseTalk"))).expanduser(),
            musetalk_python=Path(_env("MUSETALK_PYTHON", str(engine_root / "venvs" / "musetalk" / "bin" / "python"))).expanduser(),
            default_motion_backend=_env("CONTENT_FACTORY_MOTION_BACKEND", "svd"),
            default_voice_backend=_env("CONTENT_FACTORY_VOICE_BACKEND", "piper"),
            default_lipsync_backend=_env("CONTENT_FACTORY_LIPSYNC_BACKEND", "auto"),
            width=int(_env("CONTENT_FACTORY_VIDEO_WIDTH", "512")),
            height=int(_env("CONTENT_FACTORY_VIDEO_HEIGHT", "288")),
            fps=int(_env("CONTENT_FACTORY_VIDEO_FPS", "8")),
            max_shot_seconds=float(_env("CONTENT_FACTORY_MAX_SHOT_SECONDS", "4.0")),
        )

    def ensure_dirs(self) -> None:
        for path in (self.engine_root, self.models_root, self.cache_root, self.piper_voice_dir):
            path.mkdir(parents=True, exist_ok=True)
