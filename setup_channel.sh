#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
MODE="${1:---cards}"
case "$MODE" in --cards|--manim) ;; *) echo 'Usage: bash setup_channel.sh [--cards|--manim]'; exit 2;; esac
command -v ffmpeg >/dev/null || { echo 'Install FFmpeg first. macOS: brew install ffmpeg'; exit 1; }
PY="${PYTHON_BIN:-python3}"
"$PY" -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required; 3.12 recommended"'
if [[ ! -x .venv/bin/python ]]; then "$PY" -m venv .venv; fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[voice,research,browser]'
if [[ "$MODE" == --manim ]]; then
  if [[ "$(uname -s)" == "Darwin" ]]; then
    command -v brew >/dev/null || {
      echo 'Homebrew is required for Manim native dependencies on macOS.'
      echo 'Install Homebrew, then rerun: bash setup_channel.sh --manim'
      exit 1
    }
    brew list cairo >/dev/null 2>&1 || brew install cairo
    brew list pkg-config >/dev/null 2>&1 || brew install pkg-config
  fi
  .venv/bin/python -m pip install -e '.[channel]'
  .venv/bin/python -m manim checkhealth || true
fi
.venv/bin/python -m playwright install chromium
if [[ ! -f .env ]]; then cp .env.example .env; fi
DEFAULT_STUDY_VOICE="${CONTENT_FACTORY_STUDY_VOICE:-en_US-ryan-medium}"
if [[ ! -f "$ROOT/models/piper/${DEFAULT_STUDY_VOICE}.onnx" ]]; then
  echo "[VOICE] Installing default U.S. study narrator: ${DEFAULT_STUDY_VOICE}."
  bash scripts/download_voice.sh "$DEFAULT_STUDY_VOICE" || echo '[VOICE] Default Piper download failed; a matching macOS U.S. voice can still be used.'
fi
if [[ ! -f "$ROOT/models/piper/en_US-lessac-medium.onnx" ]]; then
  echo '[VOICE] Installing optional U.S. female narrator: en_US-lessac-medium.'
  bash scripts/download_voice.sh en_US-lessac-medium || true
fi
printf '\nReady. Study defaults: U.S. English + warm U.S. male narrator.\n'
printf 'Run: bash run_topic.sh --category technical\n'
printf 'Premium local voice: bash scripts/setup_kokoro_voice.sh\n'
printf 'Voice choices: bash run_topic.sh --list-voices\n'
