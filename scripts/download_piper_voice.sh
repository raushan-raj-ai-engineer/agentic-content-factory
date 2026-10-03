#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
VOICE_NAME="${2:-}"

if [[ -z "$VOICE_NAME" ]]; then
  echo "Usage:"
  echo "  bash scripts/download_piper_voice.sh $(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd) <VOICE_NAME>"
  echo
  echo "List available voices:"
  echo "  cd $(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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
