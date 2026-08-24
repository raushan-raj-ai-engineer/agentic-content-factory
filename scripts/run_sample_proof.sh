#!/usr/bin/env bash
set -euo pipefail
ROOT="${CONTENT_FACTORY_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$ROOT"
OUTDIR="$ROOT/artifacts/v19_6_proof"
mkdir -p "$OUTDIR"
IMG="$ROOT/sample_assets/scene_01.png"
SILENT="$OUTDIR/scene1_svd_motion_silent.mp4"
VOICE="$OUTDIR/babuji.wav"
FINAL="$OUTDIR/scene1_svd_motion_voice.mp4"
TEXT='ए गुड्डू, AI कहऽ हई—कुशन हल्का झाड़ऽ।'

echo "[PROOF V19.6] 1/3 generating locked Babuji voice"
bash "$ROOT/run_own_video.sh" voice-test --speaker babuji --text "$TEXT" --out "$VOICE"

echo "[PROOF V19.6] 2/3 generating REAL SVD image-to-video motion (8GB low-memory profile)"
CONTENT_FACTORY_VIDEO_WIDTH=448 CONTENT_FACTORY_VIDEO_HEIGHT=256 SVD_FRAMES=10 SVD_STEPS=20 SVD_MOTION_BUCKET=100 SVD_NOISE_AUG=0.02 SVD_EXPORT_FPS=3 \
  bash "$ROOT/run_own_video.sh" motion-proof --motion svd --image "$IMG" --prompt 'image-conditioned motion' --out "$SILENT" --seed 42

echo "[PROOF V19.6] 3/3 muxing verified V19.2 voice"
# Extend only the final generated frame if voice is a little longer; generated motion itself is not replaced by a static fallback.
VDUR=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$SILENT")
ADUR=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$VOICE")
TARGET=$(python3 - <<PY
v=float('$VDUR'); a=float('$ADUR'); print(f"{max(v,a):.3f}")
PY
)
ffmpeg -y -hide_banner -loglevel error -i "$SILENT" -i "$VOICE" \
  -filter_complex "[0:v]tpad=stop_mode=clone:stop_duration=2,trim=duration=$TARGET[v];[1:a]apad=pad_dur=2,atrim=duration=$TARGET[a]" \
  -map '[v]' -map '[a]' -c:v libx264 -crf 19 -preset veryfast -pix_fmt yuv420p -c:a aac -b:a 192k "$FINAL"

python3 - "$FINAL" <<'PY'
import json, subprocess, sys
p=sys.argv[1]
data=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type,codec_name,sample_rate,channels','-of','json',p],text=True))
streams=data.get('streams',[])
video=next((s for s in streams if s.get('codec_type')=='video'),None)
audio=next((s for s in streams if s.get('codec_type')=='audio'),None)
dur=float((data.get('format') or {}).get('duration') or 0)
if not video or not audio: raise SystemExit('[PROOF QA V19.6] FAIL: expected video+audio')
if dur < 3.0: raise SystemExit(f'[PROOF QA V19.6] FAIL: duration={dur:.2f}s')
print(f"[PROOF QA V19.6] PASS; duration={dur:.2f}s; video={video.get('codec_name')}; audio={audio.get('codec_name')} {audio.get('sample_rate')}Hz {audio.get('channels')}ch")
PY
printf '[PROOF V19.6] %s\n' "$FINAL"
