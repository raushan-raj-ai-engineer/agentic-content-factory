#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export CONTENT_FACTORY_PROJECT_ROOT="$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export PATH="${CONTENT_FACTORY_VIDEO_ENGINE_HOME:-$ROOT/.local-video-engine}/bin:$PATH"
PY="$ROOT/.venv/bin/python"
[[ -x "$PY" ]] || { echo "Run bash setup.sh first" >&2; exit 2; }
exec "$PY" -m content_factory.local_video "$@"
