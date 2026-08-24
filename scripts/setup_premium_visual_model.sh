#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-/Users/maa/agentic-content-factory}"
ENV="$PROJECT/.visual-venv"
PYTHON="${PYTHON:-python3}"

echo "Premium local visual model setup"
echo "Project: $PROJECT"
echo

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This premium setup is intended for macOS Apple Silicon."
  exit 1
fi

ARCH="$(uname -m)"
if [[ "$ARCH" != "arm64" ]]; then
  echo "Expected Apple Silicon arm64; found: $ARCH"
  exit 1
fi

MEM_BYTES="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"
MEM_GB="$(( MEM_BYTES / 1024 / 1024 / 1024 ))"

echo "Detected unified memory: ~${MEM_GB} GB"

if (( MEM_GB < 12 )); then
  echo
  echo "WARNING:"
  echo "Z-Image-Turbo can be memory-heavy on an 8 GB Mac."
  echo "The installer will still use MFLUX quantization, but creative runs"
  echo "may be constrained by hardware. Factual videos remain lightweight."
  echo
fi

if [[ ! -d "$ENV" ]]; then
  "$PYTHON" -m venv "$ENV"
fi

"$ENV/bin/python" -m pip install --upgrade pip setuptools wheel
"$ENV/bin/python" -m pip install --upgrade "mflux==0.18.0"

"$ENV/bin/python" - <<'PY'
from mflux.models.z_image import ZImageTurbo
print("MFLUX import: OK")
print("Z-Image-Turbo class: OK")
PY

echo
echo "PREMIUM VISUAL MODEL RUNTIME INSTALLED"
echo
echo "First creative generation will download model weights once."
echo "Model: Tongyi-MAI/Z-Image-Turbo"
echo "Backend: Apple MLX via MFLUX"
echo
echo "Check:"
echo "  bash $PROJECT/scripts/check_visual_engine.sh"
