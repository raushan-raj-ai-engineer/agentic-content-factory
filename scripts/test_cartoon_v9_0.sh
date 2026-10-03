#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

cd "$PROJECT"
source .venv/bin/activate
export PYTHONPATH="$PROJECT/src${PYTHONPATH:+:$PYTHONPATH}"

python - <<'PY'
from content_factory.cartoon.characters import (
    background_ids,
    character_registry,
    default_cast,
)
from content_factory.cartoon.language import (
    available_languages,
    load_language_pack,
)
from content_factory.cartoon.models import (
    CartoonEpisodePlan,
)

expected = {
    "english",
    "hindi",
    "hinglish",
    "magahi",
    "bhojpuri",
}

available = set(
    available_languages()
)

assert expected.issubset(
    available
), (expected, available)

print("Initial 5 language packs: OK")

for code in sorted(expected):
    pack = load_language_pack(
        code
    )

    assert pack.code == code
    assert pack.native_writing_rule
    assert pack.humor_guidance
    assert pack.voice_locale_preferences

print("Native-writing language profiles: OK")

assert load_language_pack(
    "hi"
).code == "hindi"

assert load_language_pack(
    "en"
).code == "english"

assert load_language_pack(
    "मगही"
).code == "magahi"

assert load_language_pack(
    "भोजपुरी"
).code == "bhojpuri"

print("Language aliases: OK")

registry = character_registry()

for required in (
    "guddu",
    "bittu",
    "chacha",
    "mai",
    "babuji",
):
    assert required in registry

assert len(
    default_cast()
) >= 4

print("Persistent original character registry: OK")

backgrounds = set(
    background_ids()
)

for required in (
    "courtyard",
    "tea_shop",
    "living_room",
    "market",
    "classroom",
):
    assert required in backgrounds

print("Reusable background registry: OK")

schema = CartoonEpisodePlan.model_json_schema()

assert "scenes" in schema["properties"]
assert "language_code" in schema["properties"]
assert "characters" in schema["properties"]

print("Animation-ready structured episode schema: OK")

print()
print("MULTILINGUAL CARTOON CORE V9.0 TESTS PASSED")
PY

echo
echo "CLI languages:"
bash "$PROJECT/run_cartoon.sh" --list-languages

echo
echo "CLI characters:"
bash "$PROJECT/run_cartoon.sh" --list-characters
