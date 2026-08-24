#!/usr/bin/env bash
set -euo pipefail

PROJECT="$(cd "$(dirname "$0")" && pwd)"

cd "$PROJECT"
source "$PROJECT/.venv/bin/activate"

export PYTHONPATH="$PROJECT/src${PYTHONPATH:+:$PYTHONPATH}"

exec python -m content_factory.cartoon.cli "$@"
