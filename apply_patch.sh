#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-.}"
cd "$ROOT"

required=(
  "src/content_factory/agents/base.py"
  "src/content_factory/agents/__init__.py"
  "src/content_factory/research/base.py"
  "src/content_factory/orchestration/state.py"
  "src/content_factory/voice/base.py"
  "src/content_factory/voice/local.py"
  "src/content_factory/video/local.py"
)

missing=0
for f in "${required[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "[MISSING] $f"
    missing=1
  fi
done

if [[ "$missing" -ne 0 ]]; then
  echo
  echo "Refusing to apply overlay because original project files are missing."
  echo "Restore the missing files first, then run this script again."
  exit 2
fi

PATCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
files=(
  "configs/local.yaml"
  "src/content_factory/config/settings.py"
  "src/content_factory/human/approval.py"
  "src/content_factory/agents/research_planner.py"
  "src/content_factory/agents/trend_researcher.py"
  "src/content_factory/agents/content_producer.py"
  "src/content_factory/research/youtube.py"
  "src/content_factory/research/factory.py"
  "src/content_factory/orchestration/workflow.py"
  "src/content_factory/visual/local.py"
  "src/content_factory/main.py"
)

for f in "${files[@]}"; do
  mkdir -p "$(dirname "$f")"
  cp "$PATCH_DIR/$f" "$f"
  echo "[PATCHED] $f"
done

echo
python -m pip install -e .
echo
python - <<'PY'
from content_factory.agents.base import Agent
from content_factory.main import main
print("[OK] content_factory imports successfully")
PY
