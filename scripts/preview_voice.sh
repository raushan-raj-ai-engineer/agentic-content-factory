#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ -x .venv/bin/python ]] || { echo 'Run bash setup_channel.sh --cards first' >&2; exit 2; }
PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" .venv/bin/python scripts/preview_voice.py "$@"
