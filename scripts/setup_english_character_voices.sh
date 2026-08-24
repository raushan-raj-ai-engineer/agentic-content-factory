#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-/Users/maa/agentic-content-factory}"

cd "$PROJECT"
source .venv/bin/activate

mkdir -p models/piper

echo "Installing English multi-speaker character voice bank..."
echo "Voice: en_US-libritts-high"
echo "The upstream Piper model card lists 904 speakers and CC BY 4.0 dataset licensing."
echo

python -m piper.download_voices \
  --data-dir models/piper \
  en_US-libritts-high

echo
echo "Installed."
echo "Run scripts/show_voices.sh to confirm."
