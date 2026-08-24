#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-/Users/maa/agentic-content-factory}"
CACHE="$PROJECT/.cache/content_factory"

if [[ ! -d "$CACHE" ]]; then
  echo "No Content Factory cache exists."
  exit 0
fi

rm -rf "$CACHE"
mkdir -p "$CACHE"

echo "Cleared Content Factory performance cache:"
echo "  $CACHE"
