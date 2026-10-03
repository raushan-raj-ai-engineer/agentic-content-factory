#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
export CONTENT_FACTORY_PROJECT_ROOT="$ROOT"
export CONTENT_FACTORY_FFMPEG_PARALLEL="${CONTENT_FACTORY_FFMPEG_PARALLEL:-1}"
export CONTENT_FACTORY_LANGUAGE="${CONTENT_FACTORY_LANGUAGE:-auto}"
[[ -x .venv/bin/python ]] || { echo 'Run bash setup.sh first' >&2; exit 2; }
exec .venv/bin/python -m content_factory.main --config configs/local.yaml "$@"
