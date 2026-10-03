#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

cd "$PROJECT"
source .venv/bin/activate
export PYTHONPATH="$PROJECT/src${PYTHONPATH:+:$PYTHONPATH}"

python - <<'PY'
from content_factory.cartoon.characters import (
    character_registry,
)
from content_factory.cartoon.language import (
    available_languages,
    load_language_pack,
)

print("=" * 76)
print("MULTILINGUAL CARTOON CORE V9.0")
print("=" * 76)

print("Languages:")
for code in available_languages():
    item = load_language_pack(
        code
    )
    print(
        f"  {item.code:<10} "
        f"{item.display_name:<12} "
        f"voices={','.join(item.voice_locale_preferences)}"
    )

print()
print("Original persistent cast:")
for item in character_registry().values():
    print(
        f"  {item.id:<10} "
        f"{item.display_name:<10} "
        f"{item.role}"
    )

print()
print("V9.0 output:")
print("  structured cartoon episode plan")
print("  character-wise dialogue")
print("  emotions / poses")
print("  camera / reaction / SFX cues")
print()
print("Not in V9.0 yet:")
print("  sprite artwork")
print("  lip-sync render")
print("  final animated MP4")
PY
