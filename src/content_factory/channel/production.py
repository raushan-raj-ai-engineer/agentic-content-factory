from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from content_factory.config.settings import Settings
from content_factory.llm.factory import select_llm_provider
from content_factory.local_video.backends.voice_piper import PiperVoiceBackend
from content_factory.local_video.config import EngineConfig
from content_factory.local_video.media import (
    concat_media,
    duration_seconds,
    mux,
    normalize_audio,
    run,
    verify_audio,
)

from .catalog import CODES, lesson
from .pedagogy import (
    PEDAGOGY_VERSION,
    adaptive_tempo,
    readable_duration,
    sme_review,
    target_wpm,
    trailing_pause,
    word_count,
)
from .render import VERSION, card, render


def checked_solution(item):
    """Execute ONLY the shipped solution string, never a model-written program."""
    namespace = {}
    exec(compile(CODES[item.topic], "<shipped-solution>", "exec"), namespace)
    fn = namespace[next(name for name in namespace if name != "__builtins__")]
    inp = item.inputs
    if item.topic in ("binary-search", "two-sum"):
        actual = fn(inp["values"].copy(), inp["target"])
    elif item.topic == "move-zeroes":
        actual = fn(inp["values"].copy())
    else:
        actual = fn(inp["text"])
    if actual != item.result:
        raise RuntimeError("Algorithm trace differs from shipped executable solution")
    return {
        "passed": True,
        "result": actual,
        "method": "shipped solution output agrees with generated trace",
        "scope": "this input only; catalog regression tests cover more inputs",
    }


def stamp(seconds):
    ms = round(seconds * 1000)
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def export_text(out, scenes, durations, title, description):
    elapsed = 0.0
    captions = []
    chapters = []
    for scene, duration in zip(scenes, durations, strict=True):
        chapters.append(f"{int(elapsed) // 60:02}:{int(elapsed) % 60:02} {scene['title']}")
        import textwrap

        parts = textwrap.wrap(scene["narration"], width=66) or [scene["narration"]]
        # Leave a small visual hold at the end of each scene instead of assigning
        # subtitle text to the full padded duration.
        speech = max(0.5, duration - trailing_pause(scene.get("stage")))
        for j, text in enumerate(parts):
            captions.append(
                f"{len(captions) + 1}\n"
                f"{stamp(elapsed + speech * j / len(parts))} --> "
                f"{stamp(elapsed + speech * (j + 1) / len(parts))}\n{text}\n"
            )
        elapsed += duration

    (out / "captions.srt").write_text("\n".join(captions), encoding="utf-8")
    (out / "upload.txt").write_text(
        f"Title: {title}\n\n{description}\n\n"
        "Suggested chapters (review timing):\n"
        + "\n".join(chapters)
        + "\n\nCaptions use approximate phrase timing. Review before uploading.\n",
        encoding="utf-8",
    )
    (out / "script.md").write_text(
        "\n\n".join(
            f"## {scene['title']}\n\n"
            f"**Learning goal:** {scene.get('learning_goal') or '-'}\n\n"
            f"{scene['narration']}"
            for scene in scenes
        ),
        encoding="utf-8",
    )


def voice_backend(root, voice_name):
    cfg = EngineConfig.from_project(root)
    cfg = replace(cfg, piper_voice_map={"default": voice_name})
    backend = PiperVoiceBackend(cfg)
    backend.ensure_voice(voice_name)
    return backend


def voice_clip(backend, text, out, *, stage="explain"):
    """Generate study-paced narration and add a deliberate scene-end pause."""
    raw = out.with_suffix(".raw.wav")
    normalized = out.with_suffix(".normalized.wav")
    backend.synthesize(text, "default", raw)
    raw_seconds = duration_seconds(raw)
    tempo = adaptive_tempo(text=text, raw_seconds=raw_seconds, stage=stage)
    normalize_audio(raw, normalized, tempo=tempo)
    spoken_seconds = duration_seconds(normalized)

    pause = trailing_pause(stage)
    final_seconds = readable_duration(spoken_seconds + pause)
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(normalized),
            "-af",
            f"apad=pad_dur={pause:.3f}",
            "-t",
            f"{final_seconds:.3f}",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(out),
        ]
    )
    qa = verify_audio(out)
    words = word_count(text)
    effective_wpm = words / max(0.1, spoken_seconds) * 60.0
    return qa.duration, {
        "stage": stage,
        "words": words,
        "raw_seconds": round(raw_seconds, 3),
        "tempo": tempo,
        "target_wpm": target_wpm(stage),
        "effective_spoken_wpm": round(effective_wpm, 1),
        "trailing_pause_seconds": pause,
        "final_seconds": round(qa.duration, 3),
    }


def valid_media(path):
    try:
        return path.is_file() and duration_seconds(path) > 0
    except (ValueError, KeyError, subprocess.SubprocessError, OSError):
        return False


class NarrationRewrite(BaseModel):
    narration: str


async def _rewrite_narration_with_llm(item, llm):
    # Code, trace, values and answers remain deterministic. The selected LLM only
    # improves pedagogy and wording. One provider/model is locked before the first
    # scene and reused for every scene in this lesson.
    report = {
        "provider": llm.provider_name,
        "model": llm.model_name,
        "enhanced_scenes": 0,
        "fallback_scenes": [],
        "policy": "deterministic facts + one locked LLM for pedagogy",
    }
    for index, scene in enumerate(item.scenes, start=1):
        source = scene.narration
        prompt = f"""
You are a patient subject-matter expert teaching a complete beginner.
Rewrite ONLY the trusted narration below into clear spoken American English.

TRUSTED FACTS
- Topic: {item.title}
- Scene title: {scene.title}
- Scene stage: {scene.stage}
- Learning goal: {scene.learning_goal}
- Narration: {source}

TEACHING CONTRACT
- The TRUSTED FACTS are the only factual source. Do not add facts, numbers,
  complexity claims, prerequisites, edge cases, APIs, syntax, or results.
- Preserve every number, result, condition, caveat and qualification exactly.
- Assume the learner is new. Define jargon in plain language on first use.
- Explain WHY before WHAT when the scene contains a decision or rule.
- For a theory scene, make the definition concrete and beginner-friendly.
- You may use one tiny analogy only when it directly restates the trusted idea;
  never let an analogy introduce a new technical claim.
- Use 2 to 5 short spoken sentences, normally 30 to 75 words total.
- Use natural punctuation and short pauses. Avoid long compound sentences.
- No generic welcome, hype, filler, clickbait, or "as you can see".
- Do not mechanically read symbols; explain what they mean.
- Return JSON with only a narration string.
"""
        try:
            result = await llm.generate_structured(
                prompt,
                NarrationRewrite,
                max_retries=1,
            )
            draft = result.narration.strip()
            if not 20 <= len(draft) <= 1000:
                raise ValueError("invalid narration length")
            if word_count(draft) > 95:
                raise ValueError("narration too dense (>95 words)")
            scene.narration = draft
            report["enhanced_scenes"] += 1
        except Exception as exc:
            scene.narration = source
            report["fallback_scenes"].append(
                {"scene": index, "title": scene.title, "reason": str(exc)}
            )
    return report


def _select_channel_llm(root, provider_name, model_name):
    if provider_name is None or str(provider_name).strip().lower() in {
        "",
        "off",
        "none",
        "false",
    }:
        return None, {
            "mode": "disabled",
            "provider": None,
            "model": None,
            "locked": False,
        }

    settings = Settings.from_yaml(root / "configs" / "local.yaml")
    requested_provider = str(provider_name).strip().lower()
    requested_model = None if model_name is None else str(model_name).strip()
    try:
        selection = asyncio.run(
            select_llm_provider(
                settings,
                provider_override=requested_provider,
                model_override=requested_model or None,
            )
        )
    except RuntimeError as exc:
        # Auto enhancement is optional for the deterministic DSA path. Explicit
        # provider requests remain strict so configuration mistakes are visible.
        if requested_provider == "auto":
            return None, {
                "mode": "auto",
                "provider": None,
                "model": None,
                "locked": False,
                "available": False,
                "reason": str(exc),
            }
        raise

    return selection.provider, {
        "mode": selection.selection_mode,
        "provider": selection.provider_name,
        "model": selection.model_name,
        "locked": True,
        "requested_provider": selection.requested_provider,
    }


def _rewrite_and_release(item, llm):
    async def execute():
        try:
            return await _rewrite_narration_with_llm(item, llm)
        finally:
            await llm.release()

    return asyncio.run(execute())


def produce_dsa(
    root,
    topic,
    values,
    target,
    text,
    renderer,
    voice,
    llm_provider="auto",
    llm_model=None,
    max_scenes=None,
):
    started = time.monotonic()
    item = lesson(topic, values, target, text)
    check = checked_solution(item)
    selected_llm, llm_status = _select_channel_llm(
        root,
        llm_provider,
        llm_model,
    )
    llm_report = None
    if selected_llm is not None:
        print(
            "[LLM LOCK] "
            f"provider={selected_llm.provider_name}, "
            f"model={selected_llm.model_name}; "
            "same provider/model will be used for all lesson narration scenes."
        )
        llm_report = _rewrite_and_release(item, selected_llm)

    pedagogy = sme_review(item)
    if not pedagogy["passed"]:
        failed = [name for name, passed in pedagogy["checks"].items() if not passed]
        raise RuntimeError("SME pedagogy review failed: " + ", ".join(failed))

    backend = voice_backend(root, voice)
    if renderer == "manim":
        import importlib.util

        if not importlib.util.find_spec("manim"):
            raise RuntimeError(
                "Manim missing. Run bash setup_channel.sh, or explicitly select --renderer cards."
            )

    out = root / "artifacts" / "channel" / item.topic / uuid4().hex[:12]
    out.mkdir(parents=True)
    (out / "lesson.json").write_text(json.dumps(item.to_dict(), indent=2), encoding="utf-8")
    (out / "solution.py").write_text(item.code + "\n", encoding="utf-8")
    (out / "validation.json").write_text(json.dumps(check, indent=2), encoding="utf-8")
    (out / "pedagogy_review.json").write_text(json.dumps(pedagogy, indent=2), encoding="utf-8")
    (out / "llm_assist.json").write_text(
        json.dumps({"status": llm_status, "report": llm_report}, indent=2),
        encoding="utf-8",
    )

    scenes = item.scenes if max_scenes is None else item.scenes[:max_scenes]
    cache = root / ".cache" / "channel"
    cache.mkdir(parents=True, exist_ok=True)
    model, config = backend.ensure_voice(voice)
    signature = (
        f"{model.resolve()}:{model.stat().st_size}:{model.stat().st_mtime_ns}:"
        f"{config.read_text()}:{PEDAGOGY_VERSION}"
    )

    clips = []
    durations = []
    pacing = []
    hits = 0
    for i, scene in enumerate(scenes):
        spec = asdict(scene)
        spec.update(index=i, total=len(scenes))
        key = hashlib.sha256(
            json.dumps([VERSION, PEDAGOGY_VERSION, renderer, signature, spec], sort_keys=True).encode()
        ).hexdigest()
        cached = cache / f"{key}.mp4"
        target_clip = out / f"scene_{i:03d}.mp4"
        if valid_media(cached):
            shutil.copy2(cached, target_clip)
            hits += 1
            scene_duration = duration_seconds(target_clip)
            spoken = max(0.1, scene_duration - trailing_pause(scene.stage))
            pacing.append(
                {
                    "scene": i + 1,
                    "stage": scene.stage,
                    "cache_hit": True,
                    "words": word_count(scene.narration),
                    "target_wpm": target_wpm(scene.stage),
                    "approx_effective_wpm": round(word_count(scene.narration) / spoken * 60.0, 1),
                    "duration_seconds": round(scene_duration, 3),
                }
            )
        else:
            with tempfile.TemporaryDirectory(prefix="channel-", dir=cache) as folder:
                work = Path(folder)
                audio = work / "voice.wav"
                seconds, pace = voice_clip(
                    backend,
                    scene.narration,
                    audio,
                    stage=scene.stage,
                )
                pace.update(scene=i + 1, cache_hit=False)
                pacing.append(pace)
                spec["seconds"] = seconds
                video = work / "visual.mp4"
                render(spec, work, video, renderer)
                cooked = work / "clip.mp4"
                mux(video, audio, cooked)
                shutil.copy2(cooked, target_clip)
                temporary = cache / f"{key}.{uuid4().hex}.tmp"
                shutil.copy2(cooked, temporary)
                temporary.replace(cached)
        clips.append(target_clip)
        durations.append(duration_seconds(target_clip))
        print(
            f"[SCENE] {i + 1}/{len(scenes)} ready "
            f"stage={scene.stage} target≈{target_wpm(scene.stage)}wpm",
            flush=True,
        )

    final = out / ("preview.mp4" if max_scenes is not None else "video.mp4")
    concat_media(clips, final, reencode=True)
    export_text(
        out,
        [asdict(scene) for scene in scenes],
        durations,
        item.title,
        "Subject-matter-expert Python lesson: hook, mental model, worked trace, implementation, verification, complexity, edge cases and practice.",
    )
    (out / "pacing.json").write_text(json.dumps(pacing, indent=2), encoding="utf-8")

    thumb_source = asdict(item.scenes[1] if len(item.scenes) > 1 else item.scenes[0])
    thumb_source.update(title=item.title, index=0, total=len(scenes))
    card(thumb_source, out / "thumbnail.png", reveal=2)

    manifest = {
        "mode": "dsa",
        "renderer": renderer,
        "render_version": VERSION,
        "pedagogy_version": PEDAGOGY_VERSION,
        "topic": item.topic,
        "scenes": len(scenes),
        "duration_seconds": duration_seconds(final),
        "resolution": "1920x1080",
        "fps": 24,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "scene_cache_hits": hits,
        "llm_provider": llm_status.get("provider"),
        "llm_model": llm_status.get("model"),
        "llm_status": llm_status,
        "llm_enhanced": bool(
            selected_llm is not None
            and llm_report
            and llm_report.get("enhanced_scenes")
        ),
        "sme_review_passed": pedagogy["passed"],
        "review_required": True,
        "preview": max_scenes is not None,
        "captions": "approximate phrase timing; sidecar SRT",
        "output": final.name,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"OUTPUT: {out}")
    return out
