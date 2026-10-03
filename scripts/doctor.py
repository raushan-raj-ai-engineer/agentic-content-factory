"""Read-only setup checks. No model downloads or render jobs."""
import importlib.util
import json
import shutil
import sys
from pathlib import Path
import urllib.request

root = Path(__file__).resolve().parents[1]
checks = {name: shutil.which(name) is not None for name in ('ffmpeg', 'ffprobe', 'ollama')}
for module in ('pydantic', 'httpx', 'PIL', 'piper', 'yt_dlp'):
    checks[module] = importlib.util.find_spec(module) is not None
checks['workflow_contracts'] = (root/'src/content_factory/models/content.py').is_file()
checks['english_voice'] = all((root/'models/piper'/f'en_US-lessac-medium{ext}').is_file() for ext in ('.onnx','.onnx.json'))
try:
    with urllib.request.urlopen('http://localhost:11434/api/tags', timeout=3) as response:
        models = [x['name'] for x in json.load(response).get('models', [])]
except Exception:
    models = []
print(json.dumps({'python':sys.version.split()[0], 'checks':checks, 'ollama_models':models},indent=2))
print('Blender bridge: older blender_full module was not supplied. This release does not claim BharatVideo Blender compatibility.')
print('Missing FFmpeg? On macOS with Homebrew installed: brew install ffmpeg')
print('Missing voice? bash scripts/download_voice.sh en_US-lessac-medium')
print('Motion diffusion is optional and hardware-dependent; start with the media proof.')

if not checks["workflow_contracts"]:
    print("ERROR: incomplete extraction: src/content_factory/models/content.py is missing", file=sys.stderr)
    raise SystemExit(1)
