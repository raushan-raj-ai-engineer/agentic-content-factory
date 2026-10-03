#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
LOG_DIR="$PROJECT/logs"

mkdir -p "$LOG_DIR"

COUNT="$(find "$LOG_DIR" -maxdepth 1 -type f | wc -l | tr -d ' ')"

find "$LOG_DIR" -maxdepth 1 -type f -delete

echo "Cleared $COUNT log file(s) from:"
echo "  $LOG_DIR"
