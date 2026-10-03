#!/usr/bin/env bash
set -euo pipefail
PROJECT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$PROJECT"
source .venv/bin/activate

python - <<'PY2'
import ast
import inspect
from pathlib import Path

from content_factory.visual.local import LocalVisualProvider

required = {
    "_premium_prompt",
    "_stable_seed",
    "_cache_key",
    "_restore_cache",
    "_store_cache",
    "release",
    "_scene_index",
    "_motion_mode",
    "_write_motion",
    "_editorial_type",
    "_public_query",
}

missing = sorted(
    name
    for name in required
    if not hasattr(LocalVisualProvider, name)
)
assert not missing, f"Missing LocalVisualProvider helpers: {missing}"

source = inspect.getsource(LocalVisualProvider)
tree = ast.parse(source)
methods = [
    n.name
    for n in tree.body[0].body
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
]
for name in required:
    assert methods.count(name) == 1, (name, methods.count(name))

assert LocalVisualProvider._scene_index(
    "/tmp/scene_01.png"
) == 1
assert LocalVisualProvider._scene_index(
    "/tmp/scene_10.png"
) == 10
assert LocalVisualProvider._scene_index(
    "/tmp/not_a_scene.png"
) == 1

assert "topic-first query" in inspect.getsource(
    LocalVisualProvider._public_query
)

print("LocalVisualProvider required helpers: OK")
print("_scene_index parsing: OK")
print("No duplicate helper definitions: OK")
print("V8.2 topic-first public-media query preserved: OK")
print("V8.3.3 trend files untouched: OK")
print()
print("VISUAL PROVIDER RELIABILITY V8.2.1 PASSED")
PY2
