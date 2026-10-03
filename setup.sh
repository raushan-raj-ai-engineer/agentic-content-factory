#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
PY="${PYTHON_BIN:-python3}"
"$PY" -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required (3.12 recommended)"'
"$PY" -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e '.[voice,research,dev]'
if [[ ! -f .env ]]; then cp .env.example .env; fi
.venv/bin/python scripts/doctor.py
printf '\nSetup complete. Default study voice: en_US-ryan-medium\n'
