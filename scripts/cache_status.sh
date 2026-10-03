#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
CACHE="$PROJECT/.cache/content_factory"

mkdir -p "$CACHE"

echo "Content Factory cache:"
echo "  $CACHE"
echo

du -sh "$CACHE" 2>/dev/null || true

echo
echo "Voice cache:"
find "$CACHE/voice" -type f -name "*.wav" 2>/dev/null | wc -l | awk '{print "  WAV entries: " $1}'

echo "Visual cache:"
find "$CACHE/visual" -type f -name "*.png" 2>/dev/null | wc -l | awk '{print "  PNG entries: " $1}'
