#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

cd "$PROJECT"
source .venv/bin/activate
export PYTHONPATH="$PROJECT/src${PYTHONPATH:+:$PYTHONPATH}"

python - <<'PY'
from pathlib import Path

from content_factory.cartoon.renderer import CartoonRenderer
from content_factory.cartoon.language import load_language_pack

project = Path.cwd()
assets = project / "assets" / "cartoon_v9_1"

backgrounds = sorted((assets / "backgrounds").glob("*.png"))
sprites = sorted((assets / "sprites").glob("*/*.png"))
sfx = sorted((assets / "sfx").glob("*.wav"))

assert len(backgrounds) >= 10, len(backgrounds)
assert len(sprites) >= 95, len(sprites)
assert len(sfx) >= 8, len(sfx)

for char_id in ("guddu", "bittu", "chacha", "mai", "babuji"):
    folder = assets / "sprites" / char_id
    for rel in (
        "neutral_closed.png",
        "neutral_open.png",
        "happy_closed.png",
        "shocked_closed.png",
        "blink_overlay.png",
    ):
        assert (folder / rel).is_file(), (char_id, rel)

renderer = CartoonRenderer(
    project_root=project,
    language=load_language_pack("hindi"),
)
print("Bundled original cartoon assets: OK")
print("Renderer runtime preflight: OK")
PY

python -m content_factory.cartoon.renderer \
  --self-test \
  --project-root "$PROJECT"

python -m content_factory.cartoon.cli --help > /tmp/cartoon-v91-help.txt

grep -q -- '--render-plan' /tmp/cartoon-v91-help.txt
grep -q -- '--story-only' /tmp/cartoon-v91-help.txt

echo "Render-existing-plan CLI: OK"
echo "Story-only compatibility CLI: OK"
echo "CARTOON V9.1.2 RENDERER TESTS PASSED"
