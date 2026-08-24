#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-/Users/maa/agentic-content-factory}"

cd "$PROJECT"
source .venv/bin/activate

echo "============================================================"
echo "PIPER VOICES"
echo "============================================================"

find models/piper \
  -type f \
  -name "*.onnx" \
  -maxdepth 5 \
  -print 2>/dev/null \
  | sort || true

echo
echo "============================================================"
echo "macOS SYSTEM VOICES"
echo "============================================================"

if command -v say >/dev/null 2>&1; then
  say -v ? || true
else
  echo "macOS say command not found."
fi

echo
echo "For another Piper language, list/download voices:"
echo "  python -m piper.download_voices"
echo "  python -m piper.download_voices --data-dir models/piper <VOICE_NAME>"
