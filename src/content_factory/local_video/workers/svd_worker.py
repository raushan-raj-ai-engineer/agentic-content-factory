from __future__ import annotations

import argparse
from pathlib import Path


def _verify_frames(frames) -> None:
    import numpy as np
    if not frames:
        raise RuntimeError('SVD produced zero frames')
    means=[]; stds=[]; maxima=[]
    for frame in frames:
        arr=np.asarray(frame.convert('RGB'),dtype=np.float32)
        means.append(float(arr.mean())); stds.append(float(arr.std())); maxima.append(float(arr.max()))
    print(f"[SVD FRAME QA V19.6] frames={len(frames)}; mean={min(means):.2f}..{max(means):.2f}; std={min(stds):.2f}..{max(stds):.2f}; max={max(maxima):.0f}")
    if max(maxima) <= 8 or max(means) < 3.0:
        raise RuntimeError('BLACK_FRAME_QA_FAILED: SVD frames are black/near-black')
    # reject a degenerate all-identical clip as well
    if max(stds) < 2.0:
        raise RuntimeError('SVD_FRAME_QA_FAILED: output frames are nearly flat')


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument('--image',required=True)
    p.add_argument('--out',required=True)
    p.add_argument('--width',type=int,default=448)
    p.add_argument('--height',type=int,default=256)
    p.add_argument('--frames',type=int,default=10)
    p.add_argument('--steps',type=int,default=20)
    p.add_argument('--fps',type=int,default=6)
    p.add_argument('--export-fps',type=float,default=3.0)
    p.add_argument('--motion-bucket',type=int,default=100)
    p.add_argument('--noise-aug',type=float,default=0.02)
    p.add_argument('--seed',type=int,default=42)
    p.add_argument('--model',default='stabilityai/stable-video-diffusion-img2vid')
    p.add_argument('--cache',required=True)
    a=p.parse_args()

    import os
    os.environ.setdefault('PYTORCH_ENABLE_MPS_FALLBACK','1')
    os.environ.setdefault('PYTORCH_MPS_HIGH_WATERMARK_RATIO','1.0')

    import torch
    from PIL import Image
    from diffusers import StableVideoDiffusionPipeline
    from diffusers.utils import export_to_video

    if not torch.backends.mps.is_available():
        raise SystemExit('MPS is required for the packaged SVD Apple-Silicon backend')

    print(f"[SVD WORKER V19.6] model={a.model}; size={a.width}x{a.height}; frames={a.frames}; steps={a.steps}; motion_bucket={a.motion_bucket}; noise_aug={a.noise_aug}")

    # Load fp16 weights on CPU first. Sequential offload moves leaf modules to MPS only when needed.
    pipe=StableVideoDiffusionPipeline.from_pretrained(
        a.model,
        torch_dtype=torch.float16,
        variant='fp16',
        cache_dir=a.cache,
        low_cpu_mem_usage=True,
    )
    try:
        pipe.enable_sequential_cpu_offload()
        offload='SEQUENTIAL_CPU_OFFLOAD'
    except Exception as exc:
        print(f"[SVD WORKER V19.6] sequential_offload unavailable ({type(exc).__name__}: {exc}); using direct MPS low-memory mode")
        pipe=pipe.to('mps')
        offload='DIRECT_MPS'

    # On current MPS builds, sequential offload + slicing is the safer low-memory combination.
    try: pipe.enable_attention_slicing('max')
    except Exception: pass
    try: pipe.unet.enable_forward_chunking(chunk_size=1, dim=1)
    except Exception: pass
    try: pipe.vae.enable_slicing()
    except Exception: pass
    try: pipe.vae.enable_tiling()
    except Exception: pass

    image=Image.open(a.image).convert('RGB').resize((a.width,a.height))
    generator=torch.Generator(device='cpu').manual_seed(a.seed)
    if torch.backends.mps.is_available():
        torch.mps.empty_cache()

    print(f"[SVD WORKER V19.6] device=mps; offload={offload}; dtype=float16; attention_slicing=MAX")
    result=pipe(
        image=image,
        num_frames=a.frames,
        num_inference_steps=a.steps,
        decode_chunk_size=1,
        generator=generator,
        motion_bucket_id=a.motion_bucket,
        noise_aug_strength=a.noise_aug,
        fps=a.fps,
        min_guidance_scale=1.0,
        max_guidance_scale=2.5,
    )
    frames=result.frames[0]
    _verify_frames(frames)
    out=Path(a.out)
    out.parent.mkdir(parents=True,exist_ok=True)
    export_to_video(frames,str(out),fps=a.export_fps)
    if not out.exists() or out.stat().st_size < 1024:
        raise RuntimeError('SVD export returned no usable mp4')
    print(f"[SVD WORKER V19.6] output={out}; export_fps={a.export_fps}")
    return 0

if __name__=='__main__':
    raise SystemExit(main())
