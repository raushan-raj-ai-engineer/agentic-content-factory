from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import re
import shutil
import subprocess


def require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"Required executable not found: {name}")
    return path


def run(cmd: list[str], *, cwd: Path | None = None, env: dict | None = None) -> None:
    print("[RUN]", " ".join(str(x) for x in cmd))
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, check=True)


def duration_seconds(path: Path) -> float:
    require_binary("ffprobe")
    raw = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)
    ], text=True)
    return float(json.loads(raw)["format"]["duration"])


def concat_media(clips: list[Path], out: Path) -> None:
    require_binary("ffmpeg")
    out.parent.mkdir(parents=True, exist_ok=True)
    concat = out.with_suffix(".concat.txt")
    concat.write_text("\n".join(f"file '{p.resolve().as_posix()}'" for p in clips), encoding="utf-8")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(out)])


def mux(video: Path, audio: Path, out: Path) -> None:
    require_binary("ffmpeg")
    out.parent.mkdir(parents=True, exist_ok=True)
    run([
        "ffmpeg", "-y", "-i", str(video), "-i", str(audio),
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)
    ])


@dataclass(frozen=True)
class AudioQA:
    duration: float
    sample_rate: int
    channels: int
    max_volume_db: float


def normalize_audio(src: Path, out: Path, target_lufs: float = -14.0, *, tempo: float = 1.0, bass_gain_db: float = 0.0, presence_gain_db: float = 0.0) -> None:
    """Normalize Piper output safely.

    Piper Hindi voices are commonly 22.05 kHz. Applying a 14.5 kHz low-pass
    *before* resampling is invalid because 14.5 kHz is above the 11.025 kHz
    Nyquist limit. V19.1 explicitly resamples first, then applies EQ/dynamics.
    """
    require_binary("ffmpeg")
    out.parent.mkdir(parents=True, exist_ok=True)
    if not (0.5 <= tempo <= 2.0):
        raise ValueError(f"tempo out of FFmpeg atempo range: {tempo}")
    filters = (
        "aresample=48000,"
        f"atempo={tempo:.4f},"
        "highpass=f=75,"
        "lowpass=f=14000,"
        f"equalizer=f=180:t=q:w=1:g={bass_gain_db:.2f},"
        f"equalizer=f=3400:t=q:w=1:g={presence_gain_db:.2f},"
        "acompressor=threshold=-18dB:ratio=2.2:attack=8:release=90,"
        f"loudnorm=I={target_lufs}:TP=-1.2:LRA=6"
    )
    run([
        "ffmpeg", "-y", "-i", str(src),
        "-af", filters,
        "-ar", "48000", "-ac", "2", str(out)
    ])


def verify_audio(path: Path, *, min_duration: float = 0.25, min_max_volume_db: float = -35.0) -> AudioQA:
    """Fail closed when a generated WAV is missing, silent, or malformed."""
    require_binary("ffprobe")
    require_binary("ffmpeg")
    if not path.exists() or path.stat().st_size < 256:
        raise RuntimeError(f"Audio QA failed: missing/empty file: {path}")

    probe = subprocess.check_output([
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate,channels:format=duration",
        "-of", "json", str(path)
    ], text=True)
    data = json.loads(probe)
    streams = data.get("streams") or []
    if not streams:
        raise RuntimeError(f"Audio QA failed: no audio stream: {path}")
    stream = streams[0]
    duration = float((data.get("format") or {}).get("duration") or 0.0)
    sample_rate = int(stream.get("sample_rate") or 0)
    channels = int(stream.get("channels") or 0)

    vd = subprocess.run([
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
        "-af", "volumedetect", "-f", "null", "-"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=False)
    matches = re.findall(r"max_volume:\s*(-?[0-9.]+) dB", vd.stderr)
    max_volume = float(matches[-1]) if matches else -120.0

    if duration < min_duration:
        raise RuntimeError(f"Audio QA failed: duration={duration:.3f}s < {min_duration}s")
    if sample_rate != 48000:
        raise RuntimeError(f"Audio QA failed: sample_rate={sample_rate}; expected 48000")
    if channels != 2:
        raise RuntimeError(f"Audio QA failed: channels={channels}; expected stereo")
    if max_volume < min_max_volume_db:
        raise RuntimeError(f"Audio QA failed: max_volume={max_volume:.1f} dB appears inaudible")

    return AudioQA(duration=duration, sample_rate=sample_rate, channels=channels, max_volume_db=max_volume)


def concat_wavs_with_gaps(inputs: list[Path], out: Path, gap_seconds: float = 0.35) -> None:
    """Concatenate WAV files with short silence gaps for A/B voice comparison."""
    require_binary("ffmpeg")
    if not inputs:
        raise ValueError("no audio inputs")
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y"]
    for p in inputs:
        cmd += ["-i", str(p)]
    parts = []
    labels = []
    for i in range(len(inputs)):
        parts.append(f"[{i}:a]aresample=48000,aformat=sample_fmts=s16:channel_layouts=stereo[a{i}]")
        labels.append(f"[a{i}]")
        if i < len(inputs) - 1:
            parts.append(f"anullsrc=r=48000:cl=stereo:d={gap_seconds:.3f}[g{i}]")
            labels.append(f"[g{i}]")
    parts.append("".join(labels) + f"concat=n={len(labels)}:v=0:a=1[outa]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[outa]", "-ar", "48000", "-ac", "2", str(out)]
    run(cmd)
