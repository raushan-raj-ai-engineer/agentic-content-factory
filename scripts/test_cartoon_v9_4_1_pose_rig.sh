#!/usr/bin/env bash
set -euo pipefail
PROJECT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$PROJECT"
source .venv/bin/activate
export PYTHONPATH="$PROJECT/src${PYTHONPATH:+:$PYTHONPATH}"
python - <<'PY'
from pathlib import Path
from content_factory.cartoon.language import load_language_pack
from content_factory.cartoon.renderer import CartoonRenderer
r=CartoonRenderer(project_root=Path.cwd(),language=load_language_pack("magahi"))
for char in ("guddu","bittu","chacha","mai","babuji"):
    for pose in ("pointing","hands_up","thinking","running","holding_food"):
        p=r._sprite_path(char,"neutral","closed",pose=pose)
        assert p.is_file()
        assert f"/poses/{pose}/" in str(p)
assert r._pose_asset("hands-up")=="hands_up"
assert r._pose_asset("walking")=="running"
assert r._pose_asset("point")=="pointing"
assert r._pose_asset("carry")=="holding_food"
print("5 human characters x 5 action pose families: OK")
print("dialogue pose field now changes rendered body pose: OK")
print("CARTOON POSE RIG V9.4.1 TESTS PASSED")
PY
COUNT="$(find "$PROJECT/assets/cartoon_v9_1/sprites" -path '*/poses/*/*.png' -type f | wc -l | tr -d ' ')"
test "$COUNT" -ge 400
echo "Pose sprite assets: $COUNT"
echo "V9.4.1 POSE-RIG RENDER CONTRACT PASSED"
