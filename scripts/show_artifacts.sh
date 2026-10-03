#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ARTIFACT_DIR="$PROJECT/artifacts"

if [[ ! -d "$ARTIFACT_DIR" ]]; then
  echo "No artifacts folder found:"
  echo "  $ARTIFACT_DIR"
  exit 0
fi

echo "Artifacts grouped by topic:"
echo

find "$ARTIFACT_DIR" \
  -mindepth 1 \
  -maxdepth 4 \
  \( -type d -o -type f \) \
  | sed "s#^$PROJECT/##" \
  | sort
