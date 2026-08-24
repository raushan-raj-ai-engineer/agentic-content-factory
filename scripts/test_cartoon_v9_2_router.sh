#!/usr/bin/env bash
set -euo pipefail
PROJECT="${1:-/Users/maa/agentic-content-factory}"
cd "$PROJECT"
source .venv/bin/activate
export PYTHONPATH="$PROJECT/src${PYTHONPATH:+:$PYTHONPATH}"
python - <<'PY'
from content_factory.cartoon.router import route_topic, resolve_story_profile
cases={
"Litti Chor Bandar":"animal_comedy",
"Guddu ka jadui remote":"magic_fantasy",
"School homework ka hungama":"school_comedy",
"Treasure hunt in village":"adventure_chase",
"Who stole the sweets mystery":"mystery",
"Holi mela comedy":"festival_culture",
"Office boss meeting comedy":"workplace_comedy",
}
for topic,expected in cases.items():
    actual=route_topic(topic).primary
    assert actual==expected,(topic,expected,actual)
assert route_topic("A totally unusual original premise").primary=="general_comedy"
assert route_topic("homework practice").primary=="school_comedy"
assert route_topic("totally original comedy premise").primary=="general_comedy"
p=resolve_story_profile(topic="Litti Chor Bandar",language_code="magahi")
assert p["key"]=="litti_chor_bandar"
assert p["route"]=="animal_comedy"
assert p["audience"]=="kids"
assert "bandar" in p["preferred_cast"]
assert len(p["scene_directions"])==9
assert len(p["scene_lines"])==9
assert p["locations"][0]=="outdoor_kitchen"
print("Broad route taxonomy: OK")
print("Unknown topic -> general_comedy fallback: OK")
print("Latin keyword boundary false positives blocked: OK")
print("Litti Chor Bandar -> animal + food + village + kids semantics: OK")
print("Magahi/Bihari 9-scene story pack: OK")
print("UNIVERSAL CARTOON ROUTER V9.2 TESTS PASSED")
PY
