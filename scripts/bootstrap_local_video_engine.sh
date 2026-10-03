#!/usr/bin/env bash
set -euo pipefail

ROOT="${CONTENT_FACTORY_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ENGINE_HOME="${CONTENT_FACTORY_VIDEO_ENGINE_HOME:-$ROOT/.local-video-engine}"
VENV_HOME="$ENGINE_HOME/venvs"
DO_VOICE=0
DO_MOTION=0
DO_LIPSYNC=0
DO_ALL=0

if [[ $# -eq 0 ]]; then
  echo "Usage: bash scripts/bootstrap_local_video_engine.sh --voice | --motion | --lipsync | --all" >&2
  exit 2
fi
for a in "$@"; do
  case "$a" in
    --voice) DO_VOICE=1 ;;
    --motion) DO_MOTION=1 ;;
    --lipsync) DO_LIPSYNC=1 ;;
    --all) DO_ALL=1 ;;
    *) echo "Unknown option: $a" >&2; exit 2 ;;
  esac
done
[[ "$DO_ALL" == 1 ]] && DO_VOICE=1 && DO_MOTION=1 && DO_LIPSYNC=1

mkdir -p "$ENGINE_HOME" "$VENV_HOME" "$ENGINE_HOME/models/piper"

choose_py310() {
  if command -v python3.10 >/dev/null 2>&1; then
    command -v python3.10
    return
  fi
  if command -v brew >/dev/null 2>&1; then
    echo "[BOOTSTRAP] Installing Python 3.10 for video-model compatibility..." >&2
    brew install python@3.10 >&2
    if command -v python3.10 >/dev/null 2>&1; then command -v python3.10; return; fi
    if [[ -x "$(brew --prefix python@3.10)/bin/python3.10" ]]; then echo "$(brew --prefix python@3.10)/bin/python3.10"; return; fi
  fi
  echo "python3"
}
PY310="python3"
if [[ "$DO_MOTION" == 1 || "$DO_LIPSYNC" == 1 ]]; then PY310="$(choose_py310)"; fi

if command -v brew >/dev/null 2>&1; then
  command -v ffmpeg >/dev/null 2>&1 || brew install ffmpeg
  command -v git-lfs >/dev/null 2>&1 || brew install git-lfs
fi

if [[ "$DO_VOICE" == 1 ]]; then
  echo "[BOOTSTRAP] Installing core and voice dependencies in the project environment"
  bash "$ROOT/setup.sh"
fi

if [[ "$DO_MOTION" == 1 ]]; then
  echo "[BOOTSTRAP] Stable Video Diffusion low-memory Apple-Silicon backend"
  "$PY310" -m venv "$VENV_HOME/svd"
  "$VENV_HOME/svd/bin/python" -m pip install -U pip setuptools wheel
  "$VENV_HOME/svd/bin/python" -m pip install \
    "torch" "torchvision" \
    "diffusers>=0.36,<0.40" \
    "transformers>=4.46" "accelerate>=1.2" \
    "safetensors>=0.4" "huggingface_hub>=0.27" \
    "pillow>=10" "imageio>=2.34" "imageio-ffmpeg>=0.5"
  echo "[BOOTSTRAP] SVD dependencies installed. Model weights download on first proof."
  echo "[BOOTSTRAP] NOTE: SVD checkpoint is large; keep sufficient free disk space."
  echo "[BOOTSTRAP] AnimateDiff is retired on the M2 8GB profile after reproducible NaN latents."
fi

if [[ "$DO_LIPSYNC" == 1 ]]; then
  echo "[BOOTSTRAP] MuseTalk lip-sync (CUDA recommended; not auto-enabled on Apple Silicon)"
  if [[ "$(uname -s)" == "Darwin" ]]; then
    echo "[BOOTSTRAP] SKIP: V19 does not auto-install MuseTalk on macOS because current upstream is CUDA-oriented."
    echo "[BOOTSTRAP] Use --lipsync off on the M2; install MuseTalk on your own NVIDIA worker later."
  else
    if [[ ! -d "$ENGINE_HOME/MuseTalk/.git" ]]; then
      git clone --depth 1 https://github.com/TMElyralab/MuseTalk.git "$ENGINE_HOME/MuseTalk"
    fi
    "$PY310" -m venv "$VENV_HOME/musetalk"
    "$VENV_HOME/musetalk/bin/python" -m pip install -U pip
    if [[ -f "$ENGINE_HOME/MuseTalk/requirements.txt" ]]; then
      "$VENV_HOME/musetalk/bin/python" -m pip install -r "$ENGINE_HOME/MuseTalk/requirements.txt"
    fi
    echo "[BOOTSTRAP] MuseTalk repo/dependencies installed; follow upstream model-weight download if required."
  fi
fi

echo "CONTENT FACTORY LOCAL VIDEO BOOTSTRAP COMPLETE"
