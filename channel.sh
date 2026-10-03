#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
[[ -x .venv/bin/python ]] || { echo 'Run bash setup_channel.sh --cards first'; exit 1; }
exec .venv/bin/python -m content_factory.channel --project "$ROOT" "$@"
