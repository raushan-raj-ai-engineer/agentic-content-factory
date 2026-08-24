from __future__ import annotations

from dataclasses import dataclass, asdict
import json
import platform
import shutil
import subprocess
import sys


@dataclass
class HardwareReport:
    platform: str
    machine: str
    python: str
    total_memory_gb: float | None
    torch_available: bool
    mps_available: bool
    cuda_available: bool
    ffmpeg: bool
    ffprobe: bool
    git: bool

    def to_dict(self):
        return asdict(self)


def _memory_gb() -> float | None:
    try:
        if platform.system() == "Darwin":
            raw = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
            return round(int(raw) / (1024 ** 3), 2)
        if platform.system() == "Linux":
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return round(kb / (1024 ** 2), 2)
    except Exception:
        pass
    return None


def detect_hardware() -> HardwareReport:
    torch_available = mps = cuda = False
    try:
        import torch
        torch_available = True
        mps = bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())
        cuda = torch.cuda.is_available()
    except Exception:
        pass
    return HardwareReport(
        platform=platform.system(),
        machine=platform.machine(),
        python=sys.version.split()[0],
        total_memory_gb=_memory_gb(),
        torch_available=torch_available,
        mps_available=mps,
        cuda_available=cuda,
        ffmpeg=shutil.which("ffmpeg") is not None,
        ffprobe=shutil.which("ffprobe") is not None,
        git=shutil.which("git") is not None,
    )


def print_report(report: HardwareReport) -> None:
    print(json.dumps(report.to_dict(), indent=2))
    if report.platform == "Darwin" and report.machine == "arm64":
        if report.total_memory_gb is not None and report.total_memory_gb <= 8.5:
            print("[DOCTOR] Apple Silicon 8GB detected: local full-scene LTX diffusion is BLOCKED by default.")
            print("[DOCTOR] Voice/composition are supported; use a stronger local motion worker for real I2V.")
    if not report.ffmpeg:
        print("[DOCTOR] ERROR: ffmpeg missing.")
