from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import shutil
import subprocess

from .config import EngineConfig
from .hardware import detect_hardware
from .media import concat_media, duration_seconds, mux, normalize_audio, verify_audio
from .plan import Shot, load_plan, shots_from_plan
from .backends.motion_ltx import LTXMotionBackend
from .backends.motion_animatediff import AnimateDiffMotionBackend
from .backends.motion_svd import SVDMotionBackend
from .backends.voice_piper import PiperVoiceBackend
from .backends.lipsync_musetalk import MuseTalkBackend
from .voice_profiles import profile_for


@dataclass
class RenderResult:
    output: Path
    shots: int
    lipsync_used: bool


class LocalVideoPipeline:
    def __init__(self, cfg: EngineConfig, *, motion_backend: str = "svd", voice_backend: str = "piper", lipsync_backend: str = "auto", force: bool = False):
        self.cfg = cfg
        self.force = force
        if motion_backend not in ("svd", "animatediff", "ltx"):
            raise ValueError("Unsupported motion backend; fake/static motion fallback is disabled")
        if voice_backend != "piper":
            raise ValueError("V19 packaged voice backend is piper; IndicF5 is documented as an optional future adapter")
        self.motion_backend_name = motion_backend
        self.motion = SVDMotionBackend(cfg, force=force) if motion_backend == "svd" else (AnimateDiffMotionBackend(cfg, force=force) if motion_backend == "animatediff" else LTXMotionBackend(cfg, force=force))
        self.voice = PiperVoiceBackend(cfg)
        self.lipsync_mode = lipsync_backend
        self.lipsync = MuseTalkBackend(cfg)
        self.hw = detect_hardware()

    def _use_lipsync(self) -> bool:
        if self.lipsync_mode in ("off", "none"):
            return False
        if self.lipsync_mode == "musetalk":
            if not self.hw.cuda_available:
                raise RuntimeError("MuseTalk explicit mode requires CUDA in V19; use --lipsync off on Apple Silicon")
            return True
        # auto: only use when CUDA + installed.
        return bool(self.hw.cuda_available and self.lipsync.available())

    def render_shot(self, shot: Shot, work: Path, *, seed: int) -> Path:
        tag = f"s{shot.scene_id:02d}_q{shot.shot_id:02d}"
        raw_voice = work / "audio" / f"{tag}_raw.wav"
        voice = work / "audio" / f"{tag}.wav"
        self.voice.synthesize(shot.text, shot.character_id, raw_voice)
        vp = profile_for(shot.character_id)
        normalize_audio(raw_voice, voice, target_lufs=vp.target_lufs, tempo=vp.tempo, bass_gain_db=vp.bass_gain_db, presence_gain_db=vp.presence_gain_db)
        print(f"[VOICE PROFILE V19.2] speaker={shot.character_id}; profile={vp.label}; tempo={vp.tempo:.2f}; bass={vp.bass_gain_db:+.1f}dB; presence={vp.presence_gain_db:+.1f}dB")
        qa = verify_audio(voice)
        print(f"[VOICE QA V19.1] {tag}; duration={qa.duration:.2f}s; max_volume={qa.max_volume_db:.1f}dB")
        seconds = min(max(duration_seconds(voice) + 0.25, 1.5), self.cfg.max_shot_seconds)
        motion = work / "motion" / f"{tag}.mp4"
        self.motion.generate(
            shot.source_image, shot.motion_prompt, motion,
            seconds=seconds, fps=self.cfg.fps, width=self.cfg.width, height=self.cfg.height,
            seed=seed + shot.scene_id * 100 + shot.shot_id,
        )
        video_for_mux = motion
        used_sync = False
        if self._use_lipsync():
            synced = work / "synced" / f"{tag}.mp4"
            video_for_mux = self.lipsync.sync(motion, voice, synced)
            used_sync = True
        clip = work / "clips" / f"{tag}.mp4"
        mux(video_for_mux, voice, clip)
        return clip

    def render_plan(self, plan_path: Path, image_dir: Path, out: Path, *, max_scenes: int | None = None, max_shots_per_scene: int | None = None, seed: int = 42) -> RenderResult:
        self.cfg.ensure_dirs()
        if self.motion_backend_name in ("svd", "animatediff") and not self.force:
            raise RuntimeError("V19.6 acceptance gate: full-plan local diffusion rendering is blocked until the one-scene proof is approved. Run scripts/run_sample_proof.sh first; --force is only for deliberate experiments.")
        plan = load_plan(plan_path)
        shots = shots_from_plan(plan, image_dir, max_scenes=max_scenes, max_shots_per_scene=max_shots_per_scene)
        if not shots:
            raise RuntimeError("No shots generated from plan")
        work = out.parent / (out.stem + "_work")
        work.mkdir(parents=True, exist_ok=True)
        clips = []
        for shot in shots:
            print(f"[V19 SHOT] scene={shot.scene_id}; shot={shot.shot_id}; speaker={shot.character_id}")
            clips.append(self.render_shot(shot, work, seed=seed))
        concat_media(clips, out)
        manifest = {
            "version": "19.6.0",
            "plan": str(plan_path),
            "images": str(image_dir),
            "shots": len(shots),
            "output": str(out),
            "motion_backend": self.motion_backend_name,
            "voice_backend": "piper",
            "lipsync_backend": self.lipsync_mode,
        }
        out.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return RenderResult(output=out, shots=len(shots), lipsync_used=self._use_lipsync())
