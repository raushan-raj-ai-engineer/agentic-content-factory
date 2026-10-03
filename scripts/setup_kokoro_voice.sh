#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ -x .venv/bin/python ]] || { echo "Create .venv first" >&2; exit 2; }
.venv/bin/python -m pip install -U "kokoro-onnx>=0.6.1,<1" "soundfile>=0.13,<1"
mkdir -p models/kokoro
BASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"
MODEL="models/kokoro/kokoro-v1.0.fp16.onnx"
VOICES="models/kokoro/voices-v1.0.bin"
if [[ ! -f "$MODEL" ]]; then
  echo "[KOKORO] Downloading FP16 model (~164 MB)..."
  curl -L --fail --retry 3 "$BASE/kokoro-v1.0.fp16.onnx" -o "$MODEL.part"
  mv "$MODEL.part" "$MODEL"
fi
if [[ ! -f "$VOICES" ]]; then
  echo "[KOKORO] Downloading voice pack (~28 MB)..."
  curl -L --fail --retry 3 "$BASE/voices-v1.0.bin" -o "$VOICES.part"
  mv "$VOICES.part" "$VOICES"
fi
.venv/bin/python - <<'PY2'
from kokoro_onnx import Kokoro
k=Kokoro('models/kokoro/kokoro-v1.0.fp16.onnx','models/kokoro/voices-v1.0.bin')
voices=set(k.get_voices())
for name in ('am_michael','af_bella'):
    assert name in voices, f'{name} missing from Kokoro voice pack'
print('[KOKORO] Ready. Default male: am_michael; clear female alternative: af_bella')
PY2
