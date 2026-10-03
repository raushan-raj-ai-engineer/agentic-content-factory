#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ENV="$PROJECT/.visual-venv"

echo "============================================================"
echo "CONTENT FACTORY VISUAL ENGINE"
echo "============================================================"

if [[ -x "$ENV/bin/python" ]]; then
  echo "Premium environment : installed"

  "$ENV/bin/python" - <<'PY'
try:
    import mflux
    from mflux.models.z_image import ZImageTurbo
    print("MFLUX               : OK")
    print("Z-Image-Turbo       : OK")
except Exception as exc:
    print(f"Premium backend      : ERROR {type(exc).__name__}: {exc}")
PY
else
  echo "Premium environment : NOT INSTALLED"
  echo
  echo "Run:"
  echo "  bash $PROJECT/scripts/setup_premium_visual_model.sh"
fi

MEM_BYTES="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"
if [[ "$MEM_BYTES" =~ ^[0-9]+$ ]] && (( MEM_BYTES > 0 )); then
  python3 - "$MEM_BYTES" <<'PY'
import sys
value = int(sys.argv[1])
print(f"Unified memory      : {value / 1024**3:.1f} GB")
PY
fi

echo "Creative model      : Z-Image-Turbo / 9 steps"
echo "Creative size       : 1280x720 -> 1920x1080"
echo "Factual visuals     : Wikimedia cinematic + editorial"
echo "Final video         : 1080p30 / H.264 CRF17 / BT.709"
