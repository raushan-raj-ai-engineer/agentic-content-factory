#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VOICE="${1:-en_US-lessac-medium}"
VOICE_DIR="${PIPER_VOICE_DIR:-$ROOT/models/piper}"
mkdir -p "$VOICE_DIR"
# Honor custom trust stores; otherwise use the verified certifi CA bundle.
export SSL_CERT_FILE="${SSL_CERT_FILE:-$("$ROOT/.venv/bin/python" -m certifi)}"
"$ROOT/.venv/bin/python" -m piper.download_voices --download-dir "$VOICE_DIR" "$VOICE"
echo "Voice downloaded to $VOICE_DIR. Review its upstream model card/license before publishing."
