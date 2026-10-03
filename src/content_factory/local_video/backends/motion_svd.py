from __future__ import annotations
from pathlib import Path
import os, subprocess, json
from ..config import EngineConfig
from ..hardware import detect_hardware

class SVDMotionBackend:
    def __init__(self,cfg:EngineConfig,*,force:bool=False):
        self.cfg=cfg; self.force=force
    def validate(self)->None:
        hw=detect_hardware()
        if not self.cfg.svd_python.exists():
            raise RuntimeError(f"SVD Python venv missing: {self.cfg.svd_python}. Run: bash scripts/bootstrap_local_video_engine.sh --motion")
        if hw.platform=='Darwin' and hw.machine=='arm64':
            # Torch belongs to the isolated motion environment, not the main app.
            probe = subprocess.check_output([str(self.cfg.svd_python), '-c',
                'import torch,json; print(json.dumps({"mps":torch.backends.mps.is_available()}))'],
                text=True, timeout=60)
            if not json.loads(probe.strip().splitlines()[-1])["mps"]:
                raise RuntimeError('PyTorch MPS is unavailable in the SVD environment')
        if hw.total_memory_gb is not None and hw.total_memory_gb < 7.0 and not self.force:
            raise RuntimeError('SVD proof requires about an 8GB-class Apple Silicon machine')
    def generate(self,image:Path,prompt:str,out:Path,*,seconds:float,fps:int,width:int,height:int,seed:int)->Path:
        del prompt,seconds
        self.validate()
        worker=Path(__file__).resolve().parents[1]/'workers'/'svd_worker.py'
        out.parent.mkdir(parents=True,exist_ok=True)
        cmd=[
            str(self.cfg.svd_python),str(worker),
            '--image',str(image.resolve()),'--out',str(out.resolve()),
            '--width',str(width),'--height',str(height),
            '--frames',str(self.cfg.svd_frames),'--steps',str(self.cfg.svd_steps),
            '--fps',str(self.cfg.svd_conditioning_fps),'--export-fps',str(self.cfg.svd_export_fps),
            '--motion-bucket',str(self.cfg.svd_motion_bucket),'--noise-aug',str(self.cfg.svd_noise_aug),
            '--seed',str(seed),'--model',self.cfg.svd_model,
            '--cache',str((self.cfg.cache_root/'huggingface').resolve()),
        ]
        env=os.environ.copy(); env.setdefault('PYTORCH_ENABLE_MPS_FALLBACK','1'); env.setdefault('PYTORCH_MPS_HIGH_WATERMARK_RATIO','1.0')
        print('[MOTION SVD V19.6]',' '.join(cmd[:8]),'...')
        subprocess.run(cmd,check=True,env=env,stdin=subprocess.DEVNULL,timeout=7200)
        if not out.exists() or out.stat().st_size<1024:
            raise RuntimeError('SVD worker returned without a usable mp4')
        return out
