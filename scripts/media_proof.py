"""Offline English voice + technical graphic + video proof, no Ollama required."""
import asyncio
import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4
from content_factory.local_video.config import EngineConfig
from content_factory.local_video.backends.voice_piper import PiperVoiceBackend
from content_factory.local_video.media import normalize_audio, verify_audio, duration_seconds
from content_factory.visual.technical import TechnicalVisualRenderer
from content_factory.video.local import LocalVideoAssembler

async def main():
    root=Path(__file__).resolve().parents[1]
    out=root/'artifacts'/'media-proof'/uuid4().hex[:12]
    out.mkdir(parents=True)
    cfg=replace(EngineConfig.from_project(root),piper_voice_dir=root/'models/piper',piper_voice_map={'default':'en_US-lessac-medium'})
    text='A hash map remembers values we have already visited. For Two Sum, look for the missing partner before storing the current number. This prevents using the same position twice.'
    raw=out/'raw.wav';audio=out/'voice.wav';image=out/'visual.png';video=out/'proof.mp4'
    PiperVoiceBackend(cfg).synthesize(text,'default',raw)
    normalize_audio(raw,audio)
    verify_audio(audio)
    TechnicalVisualRenderer().render(title='Two Sum: remember the partner',description='Target 9. Read 2: need 7; store index 0. Read 7: need 2; return indices 0 and 1.',visual_type='workflow',output_path=str(image))
    image.with_suffix('.png.motion.json').write_text(json.dumps({'mode':'editorial_static'}))
    await LocalVideoAssembler().assemble([str(audio)],[str(image)],str(video))
    if abs(duration_seconds(video)-duration_seconds(audio))>0.25:
        raise RuntimeError('Media proof timing mismatch')
    print(f'Proof complete: {video}')
    print('This is a narrated diagram proof, not diffusion animation or a complete DSA lesson.')

if __name__=='__main__':asyncio.run(main())
