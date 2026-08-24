from __future__ import annotations

import argparse
from pathlib import Path


def _tensor_stats(torch, x) -> tuple[float, float, float, float]:
    x = x.detach().float().cpu()
    finite = torch.isfinite(x)
    finite_ratio = float(finite.float().mean().item()) if x.numel() else 0.0
    if not finite.any():
        return finite_ratio, float('nan'), float('nan'), float('nan')
    y = x[finite]
    return finite_ratio, float(y.mean().item()), float(y.std().item()), float(y.abs().max().item())


def _decode_latents_cpu_fp32(torch, pipe, latents, decode_chunk_size: int = 1):
    """Decode AnimateDiff latents on CPU/float32.

    Apple-Silicon MPS can successfully denoise latents yet return all-black PIL
    frames during fp16 VAE decode. We bypass that fragile path by asking the
    pipeline for latent output and decoding with the same VAE on CPU float32.
    """
    if isinstance(latents, (list, tuple)):
        latents = latents[0]
    if not torch.is_tensor(latents):
        raise RuntimeError(f"AnimateDiff latent output has unexpected type: {type(latents)!r}")
    if latents.ndim != 5:
        raise RuntimeError(f"AnimateDiff latent output has unexpected shape: {tuple(latents.shape)}")

    finite_ratio, mean, std, maxabs = _tensor_stats(torch, latents)
    print(
        f"[AD LATENT QA V19.5] finite={finite_ratio:.6f}; mean={mean:.6f}; "
        f"std={std:.6f}; maxabs={maxabs:.6f}"
    )
    if finite_ratio < 0.9999 or not (std > 1e-6):
        raise RuntimeError("AnimateDiff latent QA failed before decode; refusing black/invalid video")

    vae = pipe.vae
    vae.to(device="cpu", dtype=torch.float32)
    try:
        vae.disable_tiling()
    except Exception:
        pass
    try:
        vae.disable_slicing()
    except Exception:
        pass

    z = latents.detach().to(device="cpu", dtype=torch.float32)
    z = z / vae.config.scaling_factor
    batch_size, channels, num_frames, height, width = z.shape
    flat = z.permute(0, 2, 1, 3, 4).reshape(batch_size * num_frames, channels, height, width)

    decoded = []
    with torch.no_grad():
        for i in range(0, flat.shape[0], max(1, decode_chunk_size)):
            decoded.append(vae.decode(flat[i : i + max(1, decode_chunk_size)]).sample)
    video = torch.cat(decoded)
    video = video[None, :].reshape((batch_size, num_frames, -1) + video.shape[2:]).permute(0, 2, 1, 3, 4)
    video = video.float()
    return pipe.video_processor.postprocess_video(video=video, output_type="pil")


def _verify_pil_frames(frames) -> None:
    import numpy as np

    if not frames:
        raise RuntimeError("AnimateDiff produced zero decoded frames")
    means, stds, maxima = [], [], []
    for frame in frames:
        arr = np.asarray(frame.convert("RGB"), dtype=np.float32)
        means.append(float(arr.mean()))
        stds.append(float(arr.std()))
        maxima.append(float(arr.max()))
    print(
        f"[AD FRAME QA V19.5] frames={len(frames)}; "
        f"mean={min(means):.2f}..{max(means):.2f}; "
        f"std={min(stds):.2f}..{max(stds):.2f}; max={max(maxima):.0f}"
    )
    # All-zero / near-black / flat frames must never be exported as a successful proof.
    if max(maxima) <= 8 or max(means) < 3.0:
        raise RuntimeError("BLACK_FRAME_QA_FAILED: decoded AnimateDiff frames are black/near-black")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--image", required=True)
    p.add_argument("--prompt", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--width", type=int, default=512)
    p.add_argument("--height", type=int, default=288)
    p.add_argument("--fps", type=int, default=8)
    p.add_argument("--frames", type=int, default=8)
    p.add_argument("--steps", type=int, default=4)
    p.add_argument("--strength", type=float, default=0.42)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--repo", default="ByteDance/AnimateDiff-Lightning")
    p.add_argument("--checkpoint", default="animatediff_lightning_4step_diffusers.safetensors")
    p.add_argument("--base-model", default="stable-diffusion-v1-5/stable-diffusion-v1-5")
    p.add_argument("--cache", required=True)
    a = p.parse_args()

    import torch
    from PIL import Image
    from diffusers import AnimateDiffVideoToVideoPipeline, EulerDiscreteScheduler, MotionAdapter
    from diffusers.utils import export_to_video
    from huggingface_hub import hf_hub_download
    from safetensors.torch import load_file

    if not torch.backends.mps.is_available():
        raise SystemExit("MPS is required for the packaged Apple-Silicon proof backend")
    device = "mps"
    dtype = torch.float16
    ckpt = hf_hub_download(repo_id=a.repo, filename=a.checkpoint, cache_dir=a.cache)
    print(f"[AD WORKER V19.5] checkpoint={ckpt}")
    adapter = MotionAdapter()
    adapter.load_state_dict(load_file(ckpt, device="cpu"))
    adapter = adapter.to(dtype=dtype)

    pipe = AnimateDiffVideoToVideoPipeline.from_pretrained(
        a.base_model,
        motion_adapter=adapter,
        torch_dtype=dtype,
        cache_dir=a.cache,
        low_cpu_mem_usage=True,
    )
    pipe.scheduler = EulerDiscreteScheduler.from_config(
        pipe.scheduler.config, timestep_spacing="trailing", beta_schedule="linear"
    )
    pipe = pipe.to(device)

    # V19.4 used attention slicing. Keep it OFF for this small proof because
    # recent Diffusers/MPS regressions have produced all-black output with some
    # slicing/offload combinations. Forward chunking remains enabled.
    try:
        pipe.unet.enable_forward_chunking(chunk_size=1, dim=1)
    except Exception:
        pass
    try:
        pipe.vae.enable_slicing()
    except Exception:
        pass
    try:
        pipe.vae.enable_tiling()
    except Exception:
        pass

    image = Image.open(a.image).convert("RGB").resize((a.width, a.height))
    input_video = [image.copy() for _ in range(a.frames)]
    torch.mps.empty_cache()
    generator = torch.Generator(device="cpu").manual_seed(a.seed)

    print(
        f"[AD WORKER V19.5] device=mps frames={a.frames} size={a.width}x{a.height} "
        f"steps={a.steps} strength={a.strength:.2f} guidance=1.0 "
        f"decode=CPU_FP32 attention_slicing=OFF"
    )
    # Ask for latents so MPS never performs the fragile fp16 final VAE decode.
    result = pipe(
        video=input_video,
        prompt=a.prompt,
        negative_prompt=(
            "identity change, different person, different clothes, extra limbs, deformed hands, "
            "duplicate person, flicker, text, watermark, low quality"
        ),
        width=a.width,
        height=a.height,
        num_inference_steps=a.steps,
        guidance_scale=1.0,
        strength=a.strength,
        generator=generator,
        decode_chunk_size=1,
        output_type="latent",
    )
    latents = result.frames
    frames = _decode_latents_cpu_fp32(torch, pipe, latents, decode_chunk_size=1)
    _verify_pil_frames(frames)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    export_to_video(frames, str(out), fps=a.fps)
    if not out.exists() or out.stat().st_size < 1024:
        raise RuntimeError("AnimateDiff export returned no usable mp4")
    print(f"[AD WORKER V19.5] output={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
