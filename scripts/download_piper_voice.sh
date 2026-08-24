#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-/Users/maa/agentic-content-factory}"
VOICE_NAME="${2:-}"

if [[ -z "$VOICE_NAME" ]]; then
  echo "Usage:"
  echo "  bash scripts/download_piper_voice.sh /Users/maa/agentic-content-factory <VOICE_NAME>"
  echo
  echo "List available voices:"
  echo "  cd /Users/maa/agentic-content-factory"
  echo "  source .venv/bin/activate"
  echo "  python -m piper.download_voices"
  exit 2
fi

cd "$PROJECT"
source .venv/bin/activate

mkdir -p models/piper

python -m piper.download_voices \
  --data-dir models/piper \
  "$VOICE_NAME"

echo
echo "Downloaded: $VOICE_NAME"
echo
echo "IMPORTANT:"
echo "Review that voice's MODEL_CARD/license before using it in monetized/commercial content."
