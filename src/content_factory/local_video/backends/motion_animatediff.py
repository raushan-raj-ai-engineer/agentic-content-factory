from __future__ import annotations

from pathlib import Path
import os

from ..config import EngineConfig
from ..hardware import detect_hardware


class AnimateDiffMotionBackend:
    """Low-memory real diffusion motion for Apple Silicon.

    Uses AnimateDiff-Lightning's SD1.5 motion adapter with Diffusers'
    AnimateDiffVideoToVideoPipeline. A still image is repeated as the conditioning
    video; the diffusion model, not FFmpeg/warping, generates the output frames.
    """

    def __init__(self, cfg: EngineConfig, *, force: bool = False):
        self.cfg = cfg
        self.force = force
        self._pipe = None
        self._torch = None

    def validate(self) -> None:
        hw = detect_hardware()
        if not self.cfg.animatediff_python.exists():
            raise RuntimeError(
                f"AnimateDiff Python venv missing: {self.cfg.animatediff_python}. "
                "Run: bash scripts/bootstrap_local_video_engine.sh --motion"
            )
        if hw.platform == "Darwin" and hw.machine == "arm64":
            if not hw.mps_available:
                raise RuntimeError("Apple Silicon detected but PyTorch MPS is unavailable")
            if hw.total_memory_gb is not None and hw.total_memory_gb < 7.0 and not self.force:
                raise RuntimeError("AnimateDiff proof requires about an 8GB-class Apple Silicon machine")

    def _load(self):
        if self._pipe is not None:
            return self._pipe

        # This module is imported by the project Python, but heavy deps live in a
        # separate venv for CLI subprocess mode. In-process loading is only used
        # when the current interpreter already has the required packages.
        try:
            import torch
            from diffusers import AnimateDiffVideoToVideoPipeline, EulerDiscreteScheduler, MotionAdapter
            from huggingface_hub import hf_hub_download
            from safetensors.torch import load_file
        except Exception as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "AnimateDiff dependencies are not available in this Python. "
                "Use the packaged worker via motion-proof/render-plan after bootstrap."
            ) from exc

        device = "mps" if torch.backends.mps.is_available() else "cpu"
        dtype = torch.float16 if device == "mps" else torch.float32

        ckpt = hf_hub_download(
            repo_id=self.cfg.animatediff_repo,
            filename=self.cfg.animatediff_checkpoint,
            cache_dir=str(self.cfg.cache_root / "huggingface"),
        )
        adapter = MotionAdapter()
        adapter.load_state_dict(load_file(ckpt, device="cpu"))
        adapter = adapter.to(dtype=dtype)

        pipe = AnimateDiffVideoToVideoPipeline.from_pretrained(
            self.cfg.animatediff_base_model,
            motion_adapter=adapter,
            torch_dtype=dtype,
            cache_dir=str(self.cfg.cache_root / "huggingface"),
            low_cpu_mem_usage=True,
        )
        pipe.scheduler = EulerDiscreteScheduler.from_config(
            pipe.scheduler.config,
            timestep_spacing="trailing",
            beta_schedule="linear",
        )
        if device == "mps":
            pipe = pipe.to("mps")
        pipe.vae.enable_slicing()
        pipe.vae.enable_tiling()
        try:
            pipe.unet.enable_forward_chunking(chunk_size=1, dim=1)
        except Exception:
            pass
        pipe.set_progress_bar_config(disable=False)
        self._pipe = pipe
        self._torch = torch
        return pipe

    def _generate_in_process(self, image: Path, prompt: str, out: Path, *, fps: int, width: int, height: int, seed: int) -> Path:
        self.validate()
        from PIL import Image
        from diffusers.utils import export_to_video

        pipe = self._load()
        torch = self._torch
        assert torch is not None
        frame_count = self.cfg.animatediff_frames
        source = Image.open(image).convert("RGB").resize((width, height))
        video = [source.copy() for _ in range(frame_count)]
        generator = torch.Generator(device="cpu").manual_seed(seed)
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()

        print(
            f"[MOTION AD V19.5] backend=AnimateDiff-Lightning; frames={frame_count}; "
            f"size={width}x{height}; steps={self.cfg.animatediff_steps}; strength={self.cfg.animatediff_strength:.2f}"
        )
        result = pipe(
            video=video,
            prompt=prompt,
            negative_prompt=(
                "identity change, different person, different clothes, extra limbs, deformed hands, "
                "duplicate person, flicker, text, watermark, low quality"
            ),
            width=width,
            height=height,
            num_inference_steps=self.cfg.animatediff_steps,
            guidance_scale=1.0,
            strength=self.cfg.animatediff_strength,
            generator=generator,
            decode_chunk_size=1,
        )
        frames = result.frames[0]
        out.parent.mkdir(parents=True, exist_ok=True)
        export_to_video(frames, str(out), fps=fps)
        if not out.exists() or out.stat().st_size < 1024:
            raise RuntimeError("AnimateDiff returned no usable mp4")
        return out

    def generate(self, image: Path, prompt: str, out: Path, *, seconds: float, fps: int, width: int, height: int, seed: int) -> Path:
        # When called from the lightweight project interpreter, dispatch to the
        # isolated motion worker venv. No static fallback is allowed.
        self.validate()
        worker = Path(__file__).resolve().parents[1] / "workers" / "animatediff_worker.py"
        if not worker.exists():
            raise RuntimeError(f"AnimateDiff worker missing: {worker}")
        out.parent.mkdir(parents=True, exist_ok=True)
        import subprocess
        cmd = [
            str(self.cfg.animatediff_python), str(worker),
            "--image", str(image.resolve()),
            "--prompt", prompt,
            "--out", str(out.resolve()),
            "--width", str(width), "--height", str(height), "--fps", str(fps),
            "--frames", str(self.cfg.animatediff_frames),
            "--steps", str(self.cfg.animatediff_steps),
            "--strength", str(self.cfg.animatediff_strength),
            "--seed", str(seed),
            "--repo", self.cfg.animatediff_repo,
            "--checkpoint", self.cfg.animatediff_checkpoint,
            "--base-model", self.cfg.animatediff_base_model,
            "--cache", str((self.cfg.cache_root / "huggingface").resolve()),
        ]
        env = os.environ.copy()
        env.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
        env.setdefault("PYTORCH_MPS_HIGH_WATERMARK_RATIO", "0.0")
        print("[MOTION AD V19.5]", " ".join(cmd[:8]), "...")
        subprocess.run(cmd, check=True, env=env)
        if not out.exists() or out.stat().st_size < 1024:
            raise RuntimeError("AnimateDiff worker returned without a usable mp4")
        return out
