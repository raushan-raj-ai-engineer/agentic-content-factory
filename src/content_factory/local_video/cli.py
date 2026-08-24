from __future__ import annotations

import argparse
from pathlib import Path
import os
import sys

from .config import EngineConfig
from .hardware import detect_hardware, print_report
from .pipeline import LocalVideoPipeline
from .backends.voice_piper import PiperVoiceBackend
from .voice_profiles import profile_for, VOICE_PROFILES
from .media import normalize_audio, verify_audio, concat_wavs_with_gaps


def project_root_from_args(value: str | None) -> Path:
    if value:
        return Path(value).resolve()
    env = os.getenv("CONTENT_FACTORY_PROJECT_ROOT")
    if env:
        return Path(env).resolve()
    return Path.cwd().resolve()


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="content-factory-local-video", description="Open-source local video engine V19.6")
    p.add_argument("--project", help="agentic-content-factory root; defaults to current directory")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor")

    vt = sub.add_parser("voice-test")
    vt.add_argument("--text", required=True)
    vt.add_argument("--speaker", default="babuji")
    vt.add_argument("--out", required=True)

    vd = sub.add_parser("voice-demo")
    vd.add_argument("--out", default="artifacts/v19_2_voice_demo.wav")

    rp = sub.add_parser("render-plan")
    rp.add_argument("--plan", required=True)
    rp.add_argument("--images", required=True, help="Directory with scene_01.png, scene_02.png, ...")
    rp.add_argument("--out", required=True)
    rp.add_argument("--max-scenes", type=int)
    rp.add_argument("--max-shots-per-scene", type=int)
    rp.add_argument("--seed", type=int, default=42)
    rp.add_argument("--motion", default="svd", choices=["svd", "animatediff", "ltx"])
    rp.add_argument("--voice", default="piper", choices=["piper"])
    rp.add_argument("--lipsync", default="auto", choices=["auto", "off", "musetalk"])
    rp.add_argument("--force", action="store_true")

    mp = sub.add_parser("motion-proof")
    mp.add_argument("--image", required=True)
    mp.add_argument("--prompt", required=True)
    mp.add_argument("--out", required=True)
    mp.add_argument("--seed", type=int, default=42)
    mp.add_argument("--motion", default="svd", choices=["svd", "animatediff", "ltx"])
    mp.add_argument("--force", action="store_true")
    return p


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    root = project_root_from_args(args.project)
    cfg = EngineConfig.from_project(root)
    cfg.ensure_dirs()

    if args.cmd == "doctor":
        print("CONTENT FACTORY OWN VIDEO ENGINE V19.6")
        print_report(detect_hardware())
        print(f"engine_home={cfg.engine_root}")
        print(f"ltx_repo={cfg.ltx_repo} exists={cfg.ltx_repo.exists()}")
        print(f"ltx_python={cfg.ltx_python} exists={cfg.ltx_python.exists()}")
        print(f"svd_python={cfg.svd_python} exists={cfg.svd_python.exists()}")
        print(f"svd_model={cfg.svd_model}; frames={cfg.svd_frames}; steps={cfg.svd_steps}; motion_bucket={cfg.svd_motion_bucket}")
        print(f"animatediff_python={cfg.animatediff_python} exists={cfg.animatediff_python.exists()} (retired_for_m2_8gb=True)")
        print(f"animatediff_adapter={cfg.animatediff_repo}/{cfg.animatediff_checkpoint}")
        print(f"animatediff_base_model={cfg.animatediff_base_model}")
        print(f"piper_voice_dir={cfg.piper_voice_dir}")
        print("fake_static_motion=DISABLED")
        return 0

    if args.cmd == "voice-test":
        raw = Path(args.out).with_suffix(".raw.wav")
        out = Path(args.out)
        PiperVoiceBackend(cfg).synthesize(args.text, args.speaker, raw)
        vp = profile_for(args.speaker)
        normalize_audio(raw, out, target_lufs=vp.target_lufs, tempo=vp.tempo, bass_gain_db=vp.bass_gain_db, presence_gain_db=vp.presence_gain_db)
        qa = verify_audio(out)
        print(f"[VOICE PROFILE V19.2] speaker={args.speaker}; profile={vp.label}; tempo={vp.tempo:.2f}; bass={vp.bass_gain_db:+.1f}dB; presence={vp.presence_gain_db:+.1f}dB")
        print(f"[VOICE QA V19.2] duration={qa.duration:.2f}s; sample_rate={qa.sample_rate}; channels={qa.channels}; max_volume={qa.max_volume_db:.1f}dB")
        print(f"[VOICE TEST] {out}")
        return 0

    if args.cmd == "voice-demo":
        samples = {
            "babuji": "ए गुड्डू, ई काम धीरे करऽ। AI के बात पहिले ठीक से सुनऽ।",
            "guddu": "बाबूजी, धीरे! ई तरीका गलत हई, पहिले समझ लीं।",
            "bittu": "अरे बाबूजी, ई का कर देलऽ! अब त पूरा घर गड़बड़ हो गेल!",
            "mai": "घर साफ होतई कि पूरा घर उलट देबऽ? फोन हमरा दे दीं।",
        }
        base = Path(args.out).resolve().parent / "v19_2_voice_demo_parts"
        base.mkdir(parents=True, exist_ok=True)
        backend = PiperVoiceBackend(cfg)
        pieces = []
        for speaker in ("babuji", "guddu", "bittu", "mai"):
            raw = base / f"{speaker}.raw.wav"
            cooked = base / f"{speaker}.wav"
            backend.synthesize(samples[speaker], speaker, raw)
            vp = profile_for(speaker)
            normalize_audio(raw, cooked, target_lufs=vp.target_lufs, tempo=vp.tempo, bass_gain_db=vp.bass_gain_db, presence_gain_db=vp.presence_gain_db)
            qa = verify_audio(cooked)
            print(f"[VOICE DEMO V19.2] speaker={speaker}; profile={vp.label}; duration={qa.duration:.2f}s; max_volume={qa.max_volume_db:.1f}dB")
            pieces.append(cooked)
        out = Path(args.out).resolve()
        concat_wavs_with_gaps(pieces, out, gap_seconds=0.40)
        qa = verify_audio(out, min_duration=2.0)
        print(f"[VOICE DEMO V19.2] output={out}; duration={qa.duration:.2f}s; max_volume={qa.max_volume_db:.1f}dB")
        return 0


    if args.cmd == "motion-proof":
        if args.motion == "svd":
            from .backends.motion_svd import SVDMotionBackend
            backend = SVDMotionBackend(cfg, force=args.force)
        elif args.motion == "animatediff":
            raise RuntimeError("AnimateDiff is retired on M2 8GB after reproducible NaN latents; use --motion svd")
        else:
            from .backends.motion_ltx import LTXMotionBackend
            backend = LTXMotionBackend(cfg, force=args.force)
        out = Path(args.out).resolve()
        backend.generate(
            Path(args.image).resolve(), args.prompt, out,
            seconds=max(1.0, cfg.svd_frames / max(cfg.svd_export_fps, 1.0)), fps=int(cfg.svd_export_fps), width=cfg.width, height=cfg.height, seed=args.seed,
        )
        print(f"[MOTION PROOF V19.6] backend={args.motion}; output={out}")
        return 0

    if args.cmd == "render-plan":
        pipe = LocalVideoPipeline(cfg, motion_backend=args.motion, voice_backend=args.voice, lipsync_backend=args.lipsync, force=args.force)
        result = pipe.render_plan(
            Path(args.plan).resolve(), Path(args.images).resolve(), Path(args.out).resolve(),
            max_scenes=args.max_scenes, max_shots_per_scene=args.max_shots_per_scene, seed=args.seed,
        )
        print(f"[V19 DONE] output={result.output}; shots={result.shots}; lipsync_used={result.lipsync_used}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
