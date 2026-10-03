from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import wave
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from PIL import Image
import numpy as np

from content_factory.video.base import VideoAssembler


class LocalVideoAssembler(VideoAssembler):
    """
    1080p quality-first YouTube assembler with semantic Manim Study Mode animation.

    Photos/creative art receive cinematic movement.
    Text-heavy editorial frames receive only an extremely subtle push so text
    stays crisp and readable instead of swimming around the screen.
    """

    def __init__(
        self,
        ffmpeg_path: str = "ffmpeg",
    ) -> None:
        self._ffmpeg_path = ffmpeg_path
        self._parallel_segments = max(
            1,
            min(
                3,
                int(
                    os.getenv(
                        "CONTENT_FACTORY_FFMPEG_PARALLEL",
                        "1",
                    )
                ),
            ),
        )

        self._study_parallel = max(
            1,
            min(
                2,
                int(os.getenv("CONTENT_FACTORY_STUDY_RENDER_PARALLEL", "2")),
            ),
        )

        self._study_repair_count = 0

        print(
            "[VIDEO] V16 quality output: "
            "1080p30 / H.264 CRF17 / BT.709 / precision-motion deterministic-study-visuals self-healing-readability-temporal-semantic-study-animation."
        )

    async def assemble(
        self,
        voice_files: list[str],
        visual_files: list[str],
        output_path: str,
    ) -> int:
        if not voice_files:
            raise ValueError(
                "At least one voice file is required."
            )

        if (
            len(
                voice_files
            )
            != len(
                visual_files
            )
        ):
            raise ValueError(
                "Voice and visual file counts must match."
            )

        output = Path(
            output_path
        )
        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        segment_dir = (
            output.parent
            / (".segments-" + uuid4().hex)
        )
        segment_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        segment_files = [
            segment_dir
            / f"segment_{index:03d}.mp4"
            for index in range(
                1,
                len(
                    voice_files
                )
                + 1,
            )
        ]

        study_manim = any(
            self._motion_mode(visual) in {"study_semantic_manim", "study_storyboard_manim"}
            for visual in visual_files
        )
        semaphore = asyncio.Semaphore(self._study_parallel if study_manim else self._parallel_segments)
        if study_manim:
            print(
                f"[STUDY RENDER] parallel={self._study_parallel} "
                "(independent Manim scene subprocesses)"
            )

        async def render_one(
            index: int,
            voice: str,
            visual: str,
            target: Path,
        ) -> None:
            async with semaphore:
                await self._create_segment(
                    visual_file=visual,
                    voice_file=voice,
                    duration=self._audio_duration(
                        voice
                    ),
                    output_path=target,
                    motion_index=index,
                    motion_mode=self._motion_mode(
                        visual
                    ),
                )

        try:
            await asyncio.gather(
                *[
                    render_one(
                        index,
                        voice,
                        visual,
                        target,
                    )
                    for index, (
                        voice,
                        visual,
                        target,
                    ) in enumerate(
                        zip(
                            voice_files,
                            visual_files,
                            segment_files,
                            strict=True,
                        ),
                        start=1,
                    )
                ]
            )

            await self._concat(
                segment_files,
                output,
            )

            if self._study_animation_required(visual_files):
                await self._master_study_audio(output)

            total = sum(
                self._audio_duration(
                    voice
                )
                for voice in voice_files
            )

            if self._study_animation_required(visual_files):
                await self._validate_study_motion(
                    output=output,
                    duration=total,
                )
                self._validate_study_repair_rate(len(visual_files))
                await self._validate_study_visual_readability(output)

            return max(
                1,
                round(
                    total
                ),
            )

        finally:
            for segment in segment_files:
                segment.unlink(
                    missing_ok=True
                )

            with suppress(
                OSError
            ):
                segment_dir.rmdir()

    async def _create_segment(
        self,
        *,
        visual_file: str,
        voice_file: str,
        duration: float,
        output_path: Path,
        motion_index: int,
        motion_mode: str,
    ) -> None:
        if motion_mode in {"study_semantic_manim", "study_storyboard_manim"}:
            manifest = self._study_semantic_manifest(visual_file)
            if manifest is None:
                raise RuntimeError(
                    "Study scene has no semantic Manim plan: "
                    f"{visual_file}. Study Mode never falls back to a static PNG or zoom/pan."
                )
            await self._create_semantic_manim_segment(
                visual_file=visual_file,
                voice_file=voice_file,
                duration=duration,
                output_path=output_path,
                manifest=manifest,
            )
            return

        if motion_mode.startswith("study_"):
            raise RuntimeError(
                f"Legacy Study Mode renderer {motion_mode!r} is disabled. "
                "Regenerate visuals with semantic Manim plans."
            )

        shots = self._broll_shots(
            visual_file
        )

        if len(
            shots
        ) > 1:
            await self._create_multishot_segment(
                shots=shots,
                voice_file=voice_file,
                duration=duration,
                output_path=output_path,
                motion_index=motion_index,
            )
            return

        command = [
            self._ffmpeg_path,
            "-y",
            "-loglevel",
            "error",
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            visual_file,
            "-i",
            voice_file,
            "-t",
            str(
                duration
            ),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-vf",
            self._motion_filter(
                motion_index=motion_index,
                mode=motion_mode,
            ),
            "-c:v",
            "libx264",
            "-preset",
            os.getenv("CONTENT_FACTORY_FFMPEG_PRESET", "fast"),
            "-crf",
            "17",
            "-profile:v",
            "high",
            "-level:v",
            "4.1",
            "-pix_fmt",
            "yuv420p",
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-c:a",
            "aac",
            "-b:a",
            "384k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-shortest",
            str(
                output_path
            ),
        ]

        await self._run(
            command
        )

    async def _create_multishot_segment(
        self,
        *,
        shots: list[str],
        voice_file: str,
        duration: float,
        output_path: Path,
        motion_index: int,
    ) -> None:
        """
        Build a narration segment from 2-3 distinct stills, then mux the
        untouched WAV once. This gives factual scenes a real B-roll cut rhythm
        without altering narration timing.
        """
        usable_count = min(
            len(
                shots
            ),
            max(
                1,
                min(
                    3,
                    int(
                        duration
                        // 4.5
                    ),
                ),
            ),
        )

        selected = shots[
            :usable_count
        ]

        if len(
            selected
        ) <= 1:
            command = [
                self._ffmpeg_path,
                "-y",
                "-loglevel",
                "error",
                "-loop",
                "1",
                "-framerate",
                "30",
                "-i",
                selected[0],
                "-i",
                voice_file,
                "-t",
                str(
                    duration
                ),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-vf",
                self._motion_filter(
                    motion_index=motion_index,
                    mode="photo_pan",
                ),
                "-c:v",
                "libx264",
                "-preset",
                os.getenv("CONTENT_FACTORY_FFMPEG_PRESET", "fast"),
                "-crf",
                "17",
                "-profile:v",
                "high",
                "-level:v",
                "4.1",
                "-pix_fmt",
                "yuv420p",
                "-colorspace",
                "bt709",
                "-color_primaries",
                "bt709",
                "-color_trc",
                "bt709",
                "-c:a",
                "aac",
                "-b:a",
                "384k",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-shortest",
                str(
                    output_path
                ),
            ]

            await self._run(
                command
            )
            return

        temp_dir = output_path.parent / (
            "." + output_path.stem + ".broll"
        )
        temp_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        clip_paths: list[
            Path
        ] = []

        # Equal cut rhythm. The final mux is bounded by exact WAV duration.
        base_duration = (
            duration
            / len(
                selected
            )
        )

        try:
            for index, shot in enumerate(
                selected,
                start=1,
            ):
                clip = temp_dir / (
                    f"shot_{index:02d}.mp4"
                )

                clip_paths.append(
                    clip
                )

                await self._run(
                    [
                        self._ffmpeg_path,
                        "-y",
                        "-loglevel",
                        "error",
                        "-loop",
                        "1",
                        "-framerate",
                        "30",
                        "-i",
                        shot,
                        "-t",
                        str(
                            base_duration
                        ),
                        "-vf",
                        self._motion_filter(
                            motion_index=(
                                motion_index
                                * 10
                                + index
                            ),
                            mode="photo_pan",
                        ),
                        "-an",
                        "-c:v",
                        "libx264",
                        "-preset",
                        os.getenv("CONTENT_FACTORY_FFMPEG_PRESET", "fast"),
                        "-crf",
                        "17",
                        "-profile:v",
                        "high",
                        "-level:v",
                        "4.1",
                        "-pix_fmt",
                        "yuv420p",
                        "-colorspace",
                        "bt709",
                        "-color_primaries",
                        "bt709",
                        "-color_trc",
                        "bt709",
                        str(
                            clip
                        ),
                    ]
                )

            concat_file = temp_dir / (
                "shots.txt"
            )

            concat_file.write_text(
                "\n".join(
                    f"file '{clip.resolve()}'"
                    for clip in clip_paths
                ),
                encoding="utf-8",
            )

            silent = temp_dir / (
                "silent.mp4"
            )

            await self._run(
                [
                    self._ffmpeg_path,
                    "-y",
                    "-loglevel",
                    "error",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(
                        concat_file
                    ),
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-af",
                    "aresample=async=1:first_pts=0",
                    str(
                        silent
                    ),
                ]
            )

            await self._run(
                [
                    self._ffmpeg_path,
                    "-y",
                    "-loglevel",
                    "error",
                    "-i",
                    str(
                        silent
                    ),
                    "-i",
                    voice_file,
                    "-t",
                    str(
                        duration
                    ),
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "384k",
                    "-ar",
                    "48000",
                    "-ac",
                    "2",
                    "-shortest",
                    str(
                        output_path
                    ),
                ]
            )

            print(
                "[VIDEO B-ROLL] "
                f"{output_path.name}: "
                f"{len(selected)} shots / {duration:.1f}s"
            )

        finally:
            for clip in clip_paths:
                clip.unlink(
                    missing_ok=True
                )

            for name in (
                "shots.txt",
                "silent.mp4",
            ):
                (
                    temp_dir
                    / name
                ).unlink(
                    missing_ok=True
                )

            with suppress(
                OSError
            ):
                temp_dir.rmdir()

    @staticmethod
    def _broll_shots(
        visual_file: str,
    ) -> list[str]:
        primary = Path(
            visual_file
        )

        manifest = primary.with_suffix(
            primary.suffix
            + ".shots.json"
        )

        if not manifest.is_file():
            return [
                str(
                    primary
                )
            ]

        try:
            payload = json.loads(
                manifest.read_text(
                    encoding="utf-8"
                )
            )

            result = []

            for item in payload.get(
                "shots",
                []
            ):
                value = str(
                    item.get(
                        "path",
                        ""
                    )
                ).strip()

                if not value:
                    continue

                path = Path(
                    value
                )

                if not path.is_absolute():
                    path = (
                        primary.parent
                        / path
                    )

                if path.is_file():
                    result.append(
                        str(
                            path
                        )
                    )

            return (
                result
                if result
                else [
                    str(
                        primary
                    )
                ]
            )

        except Exception:
            return [
                str(
                    primary
                )
            ]

    @staticmethod
    def _study_semantic_manifest(visual_file: str) -> tuple[Path, dict[str, object]] | None:
        visual_path = Path(visual_file)
        sidecar = visual_path.with_suffix(visual_path.suffix + ".motion.json")
        if not sidecar.is_file():
            return None
        try:
            policy = json.loads(sidecar.read_text(encoding="utf-8"))
        except Exception:
            return None
        policy_name = str(policy.get("policy") or "")
        if policy_name not in {
            "study-animation-v3-semantic-manim",
            "study-animation-v4-storyboard",
            "study-animation-v5-cue-storyboard",
            "study-animation-v6-premium-semantic",
            "study-animation-v7-teaching-directed",
            "study-animation-v9-theory-first",
        }:
            return None
        if str(policy.get("renderer") or "") != "manim":
            return None
        manifest_name = str(policy.get("study_manifest") or "").strip()
        if not manifest_name:
            return None
        manifest_path = visual_path.parent / manifest_name
        if not manifest_path.is_file():
            return None
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if policy_name in {
            "study-animation-v4-storyboard",
            "study-animation-v5-cue-storyboard",
            "study-animation-v6-premium-semantic",
            "study-animation-v7-teaching-directed",
            "study-animation-v9-theory-first",
        }:
            objects = payload.get("objects")
            beats = payload.get("beats")
            if not isinstance(objects, list) or len(objects) < 3 or not isinstance(beats, list) or len(beats) < 4:
                return None
        else:
            archetype = str(payload.get("archetype") or "").strip()
            labels = payload.get("labels")
            if not archetype or not isinstance(labels, list):
                return None
        return manifest_path, payload

    @staticmethod
    def _repair_storyboard_spec_for_manim(spec: dict[str, object]) -> dict[str, object]:
        """Create a conservative semantic-Manim repair plan.

        This is deliberately *not* a static-image fallback. It preserves the same
        scene objects and teaching order but replaces renderer-sensitive object
        kinds/actions with basic Manim primitives that are portable across
        macOS/Linux/Windows. The repaired scene is still object-level animation.
        """
        repaired = json.loads(json.dumps(spec))
        repaired["render_repair"] = "portable-semantic-v3"
        repaired["camera_style"] = "static"

        sensitive_kinds = {"code", "terminal", "browser", "array", "table", "balance", "book", "search_ui", "context_window", "answer_panel", "point_cloud"}
        objects = repaired.get("objects")
        if isinstance(objects, list):
            for raw in objects:
                if not isinstance(raw, dict):
                    continue
                kind = str(raw.get("kind") or "node")
                if kind in sensitive_kinds:
                    # Preserve the domain label but render it as a safe semantic
                    # node. No PNG/zoom fallback is ever introduced.
                    raw["kind"] = "node"
                    raw["detail"] = []
                label = str(raw.get("label") or kind.replace("_", " ").title())
                label = "".join(ch if ord(ch) >= 32 else " " for ch in label).strip()
                raw["label"] = label[:64] or kind.replace("_", " ").title()

        beats = repaired.get("beats")
        if isinstance(beats, list):
            for raw in beats:
                if not isinstance(raw, dict):
                    continue
                action = str(raw.get("action") or "reveal")
                if action == "type_code":
                    raw["action"] = "reveal"
                elif action in {"step_code", "scan"}:
                    raw["action"] = "highlight"
                elif action in {"split", "merge", "stream"}:
                    raw["action"] = "reveal"
                elif action in {"transform", "replace"}:
                    # These can be sensitive when source/target geometry differs
                    # drastically. Highlight the destination instead.
                    raw["action"] = "highlight"
                    if raw.get("target") is None and raw.get("destination"):
                        raw["target"] = raw.get("destination")
        return repaired

    async def _create_semantic_manim_segment(
        self,
        *,
        visual_file: str,
        voice_file: str,
        duration: float,
        output_path: Path,
        manifest: tuple[Path, dict[str, object]],
    ) -> None:
        manifest_path, payload = manifest
        spec = dict(payload)
        spec["seconds"] = duration
        from content_factory.voice.timing import schedule_beats
        timing_path = Path(voice_file).with_suffix(".timing.json")
        timing = json.loads(timing_path.read_text()) if timing_path.is_file() else {}
        schedule = schedule_beats(
            spec.get("beats", []), str(spec.get("description", "")), timing, duration,
        )
        spec["beat_schedule"] = schedule["beats"]
        output_path.with_suffix(".alignment.json").write_text(
            json.dumps(schedule, indent=2), encoding="utf-8",
        )
        spec["reference_png"] = str(Path(visual_file).resolve())

        temp_dir = output_path.parent / f".manim-study-{uuid4().hex}"
        media_dir = temp_dir / "media"
        temp_dir.mkdir(parents=True, exist_ok=True)
        media_dir.mkdir(parents=True, exist_ok=True)
        spec_path = temp_dir / "scene.json"
        spec_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")

        scene_file = Path(__file__).resolve().parents[1] / "visual" / "study_manim_scene.py"
        env = os.environ.copy()
        env["STUDY_SCENE_SPEC"] = str(spec_path.resolve())
        command = [
            sys.executable,
            "-m",
            "manim",
            "render",
            "--renderer",
            "cairo",
            "--resolution",
            "1920,1080",
            "--fps",
            "30",
            "--disable_caching",
            "--media_dir",
            str(media_dir.resolve()),
            "-o",
            "study_scene.mp4",
            str(scene_file),
            "SemanticStudyScene",
        ]
        descriptor = payload.get("layout") or payload.get("archetype") or "storyboard"
        print(
            "[STUDY MANIM] "
            f"scene={Path(visual_file).name} phase={payload.get('learning_phase', 'auto')} "
            f"plan={descriptor} beats={len(payload.get('beats', []))} "
            "reference=scene-specific ambient PNG; static-PNG-primary=NO; zoom=OFF"
        )
        try:
            try:
                await self._run_process(command, env=env, timeout=1800)
            except Exception as exc:
                self._study_repair_count += 1
                error_path = Path(visual_file).with_suffix(".manim-error.log")
                error_path.write_text(
                    "Semantic Manim initial render failure\n"
                    f"scene={Path(visual_file).name}\n"
                    f"plan={payload.get('layout') or payload.get('archetype')}\n"
                    f"manifest={manifest_path}\n\n"
                    + str(exc),
                    encoding="utf-8",
                )

                repaired_spec = self._repair_storyboard_spec_for_manim(spec)
                repair_path = Path(visual_file).with_suffix(".manim-repair.json")
                repair_path.write_text(json.dumps(repaired_spec, indent=2), encoding="utf-8")
                spec_path.write_text(json.dumps(repaired_spec, indent=2), encoding="utf-8")
                print(
                    "[STUDY MANIM REPAIR] "
                    f"scene={Path(visual_file).name} plan={payload.get('layout') or payload.get('archetype')} "
                    "retrying portable semantic Manim; static-PNG-primary=NO; zoom=OFF"
                )
                try:
                    await self._run_process(command, env=env, timeout=1800)
                except Exception as repair_exc:
                    with error_path.open("a", encoding="utf-8") as handle:
                        handle.write("\n\nPortable semantic repair also failed\n")
                        handle.write(str(repair_exc))
                    print(
                        "[STUDY MANIM ERROR] "
                        f"scene={Path(visual_file).name} "
                        f"plan={payload.get('layout') or payload.get('archetype')} "
                        f"log={error_path}"
                    )
                    raise RuntimeError(
                        "Semantic Manim scene failed after portable repair: "
                        f"{Path(visual_file).name} / {payload.get('layout') or payload.get('archetype')}. "
                        f"See {error_path}"
                    ) from repair_exc
            matches = list(media_dir.rglob("study_scene.mp4"))
            if len(matches) != 1:
                raise RuntimeError(
                    "Semantic Manim renderer did not produce exactly one study_scene.mp4 "
                    f"for {manifest_path}"
                )
            rendered = matches[0]
            await self._run(
                [
                    self._ffmpeg_path,
                    "-y",
                    "-loglevel",
                    "error",
                    "-i",
                    str(rendered),
                    "-i",
                    voice_file,
                    "-filter:v",
                    "tpad=stop_mode=clone:stop_duration=1,format=yuv420p",
                    "-t",
                    f"{duration:.3f}",
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    "-r",
                    "30",
                    "-c:v",
                    "libx264",
                    "-preset",
                    os.getenv("CONTENT_FACTORY_FFMPEG_PRESET", "fast"),
                    "-crf",
                    "17",
                    "-pix_fmt",
                    "yuv420p",
                    "-colorspace",
                    "bt709",
                    "-color_primaries",
                    "bt709",
                    "-color_trc",
                    "bt709",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "384k",
                    "-ar",
                    "48000",
                    "-ac",
                    "2",
                    str(output_path),
                ]
            )
        finally:
            import shutil

            shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    async def _run_process(
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        timeout: float = 1800,
    ) -> None:
        process = await asyncio.create_subprocess_exec(
            *command,
            env=env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except (TimeoutError, asyncio.CancelledError):
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        if process.returncode != 0:
            tail = (stdout + b"\n" + stderr).decode("utf-8", errors="replace")[-5000:]
            raise RuntimeError("Semantic Manim render failed:\n" + tail)

    @staticmethod
    def _study_layer_manifest(visual_file: str) -> tuple[Path, dict[str, object]] | None:
        visual_path = Path(visual_file)
        sidecar = visual_path.with_suffix(visual_path.suffix + ".motion.json")
        if not sidecar.is_file():
            return None
        try:
            policy = json.loads(sidecar.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not bool(policy.get("layered")):
            return None
        manifest_name = str(policy.get("layer_manifest") or "").strip()
        if not manifest_name:
            return None
        manifest_path = visual_path.parent / manifest_name
        if not manifest_path.is_file():
            return None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if int(manifest.get("version") or 0) < 2:
            return None
        layers = manifest.get("layers")
        if not isinstance(layers, list) or len(layers) < 3:
            return None
        return manifest_path, manifest

    async def _create_layered_study_segment(
        self,
        *,
        visual_file: str,
        voice_file: str,
        duration: float,
        output_path: Path,
        manifest: tuple[Path, dict[str, object]],
    ) -> None:
        manifest_path, payload = manifest
        layer_dir = manifest_path.parent / f"{Path(visual_file).stem}_layers"
        base_name = str(payload.get("base") or "").strip()
        base_path = layer_dir / base_name
        if not base_path.is_file():
            raise RuntimeError(f"Study animation base layer is missing: {base_path}")

        raw_layers = payload.get("layers")
        if not isinstance(raw_layers, list):
            raise RuntimeError(f"Study animation manifest has no layers: {manifest_path}")

        layers: list[dict[str, object]] = []
        for raw in raw_layers:
            if not isinstance(raw, dict):
                continue
            filename = str(raw.get("file") or "").strip()
            path = layer_dir / filename
            if not filename or not path.is_file():
                raise RuntimeError(f"Study animation layer is missing: {path}")
            item = dict(raw)
            item["path"] = path
            layers.append(item)

        if len(layers) < 3:
            raise RuntimeError(
                f"Study animation requires at least 3 independent layers: {manifest_path}"
            )

        persistent_count = sum(1 for layer in layers if bool(layer.get("persist", True)))
        step = max(0.55, min(2.6, max(0.5, duration - 1.2) / max(1, persistent_count)))
        current = 0.25
        previous_persistent_start = 0.25
        timed: list[tuple[dict[str, object], float, float | None]] = []
        for layer in layers:
            persist = bool(layer.get("persist", True))
            kind = str(layer.get("kind") or "layer")
            if not persist or kind == "focus":
                start = min(max(0.25, previous_persistent_start + 0.28), max(0.25, duration - 0.8))
                end = min(duration - 0.05, start + min(1.25, max(0.55, step * 0.9)))
                timed.append((layer, start, end))
                continue
            start = min(current, max(0.25, duration - 0.6))
            timed.append((layer, start, None))
            previous_persistent_start = start
            current += step

        # Pack all transparent teaching elements into one spritesheet. This keeps
        # FFmpeg at three inputs (base + sprite + audio) even for complex scenes,
        # instead of opening 15-20 looped PNG decoders at once.
        sprite_path = output_path.parent / f".{output_path.stem}-study-sprite-{uuid4().hex}.png"
        sprite_rows: list[tuple[int, int, int, int]] = []
        opened: list[Image.Image] = []
        try:
            max_width = 1
            total_height = 0
            for layer, _start, _end in timed:
                image = Image.open(Path(layer["path"])).convert("RGBA")
                opened.append(image)
                max_width = max(max_width, image.width)
                total_height += image.height + 4
            sprite = Image.new("RGBA", (max_width, max(1, total_height)), (0, 0, 0, 0))
            cursor_y = 0
            for image in opened:
                sprite.alpha_composite(image, (0, cursor_y))
                sprite_rows.append((0, cursor_y, image.width, image.height))
                cursor_y += image.height + 4
            sprite.save(sprite_path, format="PNG")
        finally:
            for image in opened:
                image.close()

        try:
            command = [
                self._ffmpeg_path,
                "-y",
                "-loglevel",
                "error",
                "-loop",
                "1",
                "-framerate",
                "30",
                "-i",
                str(base_path),
                "-loop",
                "1",
                "-framerate",
                "30",
                "-i",
                str(sprite_path),
                "-i",
                voice_file,
            ]

            split_labels = "".join(f"[sprite{index}]" for index in range(1, len(timed) + 1))
            filters: list[str] = [
                "[0:v]scale=1920:1080:flags=lanczos,format=rgba,setpts=PTS-STARTPTS[base]",
                f"[1:v]format=rgba,setpts=PTS-STARTPTS,split={len(timed)}{split_labels}",
            ]
            previous = "base"
            for index, ((layer, start, end), crop) in enumerate(zip(timed, sprite_rows, strict=True), start=1):
                kind = str(layer.get("kind") or "layer")
                x = int(layer.get("x") or 0)
                y = int(layer.get("y") or 0)
                crop_x, crop_y, crop_w, crop_h = crop
                fade_d = min(0.38, max(0.18, step * 0.2))
                chain = (
                    f"[sprite{index}]crop={crop_w}:{crop_h}:{crop_x}:{crop_y},"
                    f"fade=t=in:st={start:.3f}:d={fade_d:.3f}:alpha=1"
                )
                if end is not None:
                    out_start = max(start + 0.2, end - 0.28)
                    chain += f",fade=t=out:st={out_start:.3f}:d=0.260:alpha=1"
                filters.append(chain + f"[layer{index}]")

                transition = 0.46
                if kind == "title":
                    x_expr = str(x)
                    y_expr = (
                        f"if(lt(t,{start + transition:.3f}),"
                        f"{y - 48}+48*(t-{start:.3f})/{transition:.3f},{y})"
                    )
                elif kind in {"panel_left", "text_chunk", "concept"}:
                    x_expr = (
                        f"if(lt(t,{start + transition:.3f}),"
                        f"{x - 90}+90*(t-{start:.3f})/{transition:.3f},{x})"
                    )
                    y_expr = str(y)
                elif kind in {"panel_right", "flow_box", "arrow", "focus"}:
                    x_expr = (
                        f"if(lt(t,{start + transition:.3f}),"
                        f"{x + 90}-90*(t-{start:.3f})/{transition:.3f},{x})"
                    )
                    y_expr = str(y)
                else:
                    x_expr = str(x)
                    y_expr = (
                        f"if(lt(t,{start + transition:.3f}),"
                        f"{y + 45}-45*(t-{start:.3f})/{transition:.3f},{y})"
                    )

                enable = (
                    f"gte(t,{start:.3f})"
                    if end is None
                    else f"between(t,{start:.3f},{end:.3f})"
                )
                output_label = f"v{index}"
                filters.append(
                    f"[{previous}][layer{index}]overlay="
                    f"x='{x_expr}':y='{y_expr}':enable='{enable}':format=auto[{output_label}]"
                )
                previous = output_label

            filters.append(f"[{previous}]format=yuv420p[vout]")
            command.extend(
                [
                    "-filter_complex",
                    ";".join(filters),
                    "-t",
                    str(duration),
                    "-map",
                    "[vout]",
                    "-map",
                    "2:a:0",
                    "-r",
                    "30",
                    "-c:v",
                    "libx264",
                    "-preset",
                    os.getenv("CONTENT_FACTORY_FFMPEG_PRESET", "fast"),
                    "-crf",
                    "17",
                    "-profile:v",
                    "high",
                    "-level:v",
                    "4.1",
                    "-pix_fmt",
                    "yuv420p",
                    "-colorspace",
                    "bt709",
                    "-color_primaries",
                    "bt709",
                    "-color_trc",
                    "bt709",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "384k",
                    "-ar",
                    "48000",
                    "-ac",
                    "2",
                    "-shortest",
                    str(output_path),
                ]
            )

            print(
                "[STUDY LAYERS] "
                f"scene={Path(visual_file).name} beats={len(timed)} "
                f"step≈{step:.2f}s; whole-frame zoom=OFF"
            )
            await self._run(command)
        finally:
            sprite_path.unlink(missing_ok=True)

    @staticmethod
    def _motion_filter(
        *,
        motion_index: int,
        mode: str,
    ) -> str:
        if mode == "product_hero":
            return (
                "scale=2160:1215:"
                "force_original_aspect_ratio=increase:"
                "flags=lanczos,"
                "crop=2160:1215,"
                "zoompan="
                "z='min(zoom+0.00024,1.045)':"
                "x='iw/2-(iw/zoom/2)':"
                "y='ih/2-(ih/zoom/2)':"
                "d=1:s=1920x1080:fps=30,"
                "unsharp=5:5:0.34:3:3:0.14,"
                "format=yuv420p"
            )

        if mode == "product_macro":
            x_expr = (
                "0"
                if motion_index % 2
                else "iw-iw/zoom"
            )

            return (
                "scale=2240:1260:"
                "force_original_aspect_ratio=increase:"
                "flags=lanczos,"
                "crop=2240:1260,"
                "zoompan="
                "z='min(zoom+0.00034,1.075)':"
                f"x='{x_expr}':"
                "y='ih/2-(ih/zoom/2)':"
                "d=1:s=1920x1080:fps=30,"
                "unsharp=5:5:0.36:3:3:0.15,"
                "format=yuv420p"
            )

        if mode == "product_lifestyle":
            x_expr = (
                "iw/2-(iw/zoom/2)"
                if motion_index % 2
                else "iw-iw/zoom"
            )

            return (
                "scale=2160:1215:"
                "force_original_aspect_ratio=increase:"
                "flags=lanczos,"
                "crop=2160:1215,"
                "zoompan="
                "z='min(zoom+0.00026,1.050)':"
                f"x='{x_expr}':"
                "y='ih/2-(ih/zoom/2)':"
                "d=1:s=1920x1080:fps=30,"
                "unsharp=5:5:0.32:3:3:0.13,"
                "format=yuv420p"
            )

        if mode == "product_feature":
            return (
                "scale=2112:1188:"
                "force_original_aspect_ratio=increase:"
                "flags=lanczos,"
                "crop=2112:1188,"
                "zoompan="
                "z='min(zoom+0.00018,1.032)':"
                "x='iw/2-(iw/zoom/2)':"
                "y='ih/2-(ih/zoom/2)':"
                "d=1:s=1920x1080:fps=30,"
                "unsharp=5:5:0.30:3:3:0.12,"
                "format=yuv420p"
            )

        if mode == "study_code":
            # Readability-safe movement for code/text-heavy lessons.
            # Use output-frame index (`on`) rather than cumulative zoom state so
            # FFmpeg cannot reset the animation on each looped input frame.
            return (
                "scale=2180:1226:"
                "force_original_aspect_ratio=increase:"
                "flags=lanczos,"
                "crop=2180:1226,"
                "zoompan="
                "z='1.018+0.012*sin(on/95)':"
                "x='clip(iw/2-(iw/zoom/2)+(iw-iw/zoom)*0.10*sin(on/150),0,iw-iw/zoom)':"
                "y='clip(ih/2-(ih/zoom/2)+(ih-ih/zoom)*0.08*cos(on/170),0,ih-ih/zoom)':"
                "d=1:s=1920x1080:fps=30,"
                "unsharp=5:5:0.30:3:3:0.12,"
                "format=yuv420p"
            )

        if mode == "study_diagram":
            # Directional camera path helps the eye follow architecture/diagram flow.
            direction = 1 if motion_index % 2 else -1
            return (
                "scale=2260:1271:"
                "force_original_aspect_ratio=increase:"
                "flags=lanczos,"
                "crop=2260:1271,"
                "zoompan="
                "z='1.035+0.020*sin(on/85)':"
                f"x='clip(iw/2-(iw/zoom/2)+{direction}*(iw-iw/zoom)*0.24*sin(on/120),0,iw-iw/zoom)':"
                "y='clip(ih/2-(ih/zoom/2)+(ih-ih/zoom)*0.10*cos(on/160),0,ih-ih/zoom)':"
                "d=1:s=1920x1080:fps=30,"
                "unsharp=5:5:0.30:3:3:0.12,"
                "format=yuv420p"
            )

        if mode == "study_workflow":
            # Continuous left-to-right progression for process/workflow teaching.
            direction = 1 if motion_index % 2 else -1
            return (
                "scale=2280:1283:"
                "force_original_aspect_ratio=increase:"
                "flags=lanczos,"
                "crop=2280:1283,"
                "zoompan="
                "z='1.030+0.018*sin(on/100)':"
                f"x='clip(iw/2-(iw/zoom/2)+{direction}*(iw-iw/zoom)*0.28*sin(on/140),0,iw-iw/zoom)':"
                "y='ih/2-(ih/zoom/2)':"
                "d=1:s=1920x1080:fps=30,"
                "unsharp=5:5:0.30:3:3:0.12,"
                "format=yuv420p"
            )

        if mode == "study_compare":
            # Shift attention between the two sides of a comparison frame.
            return (
                "scale=2280:1283:"
                "force_original_aspect_ratio=increase:"
                "flags=lanczos,"
                "crop=2280:1283,"
                "zoompan="
                "z='1.032+0.016*sin(on/90)':"
                "x='clip(iw/2-(iw/zoom/2)+(iw-iw/zoom)*0.32*sin(on/105),0,iw-iw/zoom)':"
                "y='ih/2-(ih/zoom/2)':"
                "d=1:s=1920x1080:fps=30,"
                "unsharp=5:5:0.30:3:3:0.12,"
                "format=yuv420p"
            )

        if mode == "study_focus":
            # Generic study explainer: gentle guided focus path, always visibly moving.
            return (
                "scale=2240:1260:"
                "force_original_aspect_ratio=increase:"
                "flags=lanczos,"
                "crop=2240:1260,"
                "zoompan="
                "z='1.035+0.025*sin(on/80)':"
                "x='clip(iw/2-(iw/zoom/2)+(iw-iw/zoom)*0.20*sin(on/110),0,iw-iw/zoom)':"
                "y='clip(ih/2-(ih/zoom/2)+(ih-ih/zoom)*0.15*cos(on/130),0,ih-ih/zoom)':"
                "d=1:s=1920x1080:fps=30,"
                "unsharp=5:5:0.30:3:3:0.12,"
                "format=yuv420p"
            )

        if mode == "editorial_static":
            # Non-study editorial content may remain nearly static for typography.
            return (
                "scale=1940:1091:"
                "force_original_aspect_ratio=increase:"
                "flags=lanczos,"
                "crop=1940:1091,"
                "zoompan="
                "z='min(zoom+0.00008,1.010)':"
                "x='iw/2-(iw/zoom/2)':"
                "y='ih/2-(ih/zoom/2)':"
                "d=1:s=1920x1080:fps=30,"
                "unsharp=5:5:0.28:3:3:0.12,"
                "format=yuv420p"
            )

        if mode == "photo_pan":
            if motion_index % 2:
                x_expr = (
                    "min((iw-iw/zoom)*(on/900),iw-iw/zoom)"
                )
            else:
                x_expr = (
                    "max((iw-iw/zoom)*(1-on/900),0)"
                )

            if motion_index % 3:
                y_expr = (
                    "ih/2-(ih/zoom/2)"
                )
            else:
                y_expr = (
                    "min((ih-ih/zoom)*(on/1200),ih-ih/zoom)"
                )

            return (
                "scale=2144:1206:"
                "force_original_aspect_ratio=increase:"
                "flags=lanczos,"
                "crop=2144:1206,"
                "zoompan="
                "z='min(zoom+0.00012,1.026)':"
                f"x='{x_expr}':"
                f"y='{y_expr}':"
                "d=1:s=1920x1080:fps=30,"
                "unsharp=5:5:0.30:3:3:0.13,"
                "format=yuv420p"
            )

        # creative_push
        return (
            "scale=2112:1188:"
            "force_original_aspect_ratio=increase:"
            "flags=lanczos,"
            "crop=2112:1188,"
            "zoompan="
            "z='min(zoom+0.00024,1.040)':"
            "x='iw/2-(iw/zoom/2)':"
            "y='ih/2-(ih/zoom/2)':"
            "d=1:s=1920x1080:fps=30,"
            "unsharp=5:5:0.30:3:3:0.13,"
            "format=yuv420p"
        )

    @staticmethod
    def _motion_mode(
        visual_path: str,
    ) -> str:
        path = Path(
            visual_path
        )

        sidecar = path.with_suffix(
            path.suffix
            + ".motion.json"
        )

        if sidecar.is_file():
            try:
                value = json.loads(
                    sidecar.read_text(
                        encoding="utf-8"
                    )
                )
                mode = str(
                    value.get(
                        "mode",
                        "",
                    )
                )

                if mode in {
                    "editorial_static",
                    "photo_pan",
                    "creative_push",
                    "product_hero",
                    "product_macro",
                    "product_lifestyle",
                    "product_feature",
                    "study_code",
                    "study_diagram",
                    "study_workflow",
                    "study_compare",
                    "study_focus",
                    "study_semantic_manim",
                    "study_storyboard_manim",
                }:
                    return mode
            except Exception:
                pass

        return "creative_push"

    @staticmethod
    def _study_animation_required(visual_files: list[str]) -> bool:
        for visual in visual_files:
            path = Path(visual)
            sidecar = path.with_suffix(path.suffix + ".motion.json")
            if not sidecar.is_file():
                continue
            try:
                payload = json.loads(sidecar.read_text(encoding="utf-8"))
            except Exception:
                continue
            if bool(payload.get("required")) and str(payload.get("policy") or "").startswith("study-animation"):
                return True
        return False

    async def _validate_study_motion(
        self,
        *,
        output: Path,
        duration: float,
    ) -> None:
        # Sample twice per second and let mpdecimate remove near-identical frames.
        # A slideshow-like render retains only roughly one frame per scene, while
        # a properly animated lesson retains a substantial share of samples.
        process = await asyncio.create_subprocess_exec(
            self._ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-i",
            str(output),
            "-vf",
            "fps=0.5,mpdecimate",
            "-an",
            "-f",
            "null",
            "-",
            "-progress",
            "pipe:1",
            "-nostats",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(
                "Study animation validation failed to inspect the rendered video: "
                + stderr.decode("utf-8", errors="replace")[-1200:]
            )

        retained = 0
        for raw in stdout.decode("utf-8", errors="replace").splitlines():
            if raw.startswith("frame="):
                try:
                    retained = max(retained, int(raw.split("=", 1)[1].strip()))
                except ValueError:
                    pass

        expected = max(1, int(duration * 0.5))
        ratio = retained / expected
        minimum = float(os.getenv("STUDY_ANIMATION_MIN_RETENTION", "0.35"))
        print(
            "[STUDY ANIMATION] "
            f"retained={retained}/{expected} sampled frames "
            f"({ratio:.0%}); minimum={minimum:.0%}"
        )
        if ratio < minimum:
            raise RuntimeError(
                "Study video motion quality gate failed: the rendered video is "
                f"too static ({ratio:.0%} motion retention; required {minimum:.0%}). "
                "Study Mode requires visible instructional animation/motion."
            )

    def _validate_study_repair_rate(self, scene_count: int) -> None:
        if scene_count <= 0:
            return
        ratio = self._study_repair_count / scene_count
        maximum = float(os.getenv("STUDY_MAX_REPAIR_RATIO", "0.15"))
        print(
            "[STUDY RENDER QUALITY] "
            f"repairs={self._study_repair_count}/{scene_count} ({ratio:.0%}); "
            f"maximum={maximum:.0%}"
        )
        if ratio > maximum:
            raise RuntimeError(
                "Study render quality gate failed: too many scenes required portable repair "
                f"({ratio:.0%}; maximum {maximum:.0%}). Fix the rich semantic renderer instead "
                "of publishing a repair-heavy lesson."
            )

    async def _study_visual_metrics(self, output: Path) -> dict[str, float]:
        """Measure mobile-first occupancy and *readable-edge* contrast.

        Earlier builds used the 25th percentile luminance of every non-background
        pixel. Dark panel fills therefore counted as unreadable "foreground"
        even when labels, strokes, and code were bright. This metric separates
        layout occupancy from the high-contrast edges that actually carry text
        and diagram readability.
        """
        width, height = 160, 90
        command = [
            self._ffmpeg_path, "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", str(output), "-vf", f"fps=0.5,scale={width}:{height}",
            "-an", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
        ]
        process = await asyncio.create_subprocess_exec(
            *command, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(
                "Study visual readability QC could not inspect final video: "
                + stderr.decode("utf-8", errors="replace")[-1200:]
            )
        frame_bytes = width * height * 3
        frame_count = len(stdout) // frame_bytes
        if frame_count < 2:
            raise RuntimeError("Study visual readability QC received too few frames")

        bg = np.array([7.0, 17.0, 31.0], dtype=np.float32)
        occupancies: list[float] = []
        edge_luma: list[float] = []
        edge_ratio: list[float] = []
        for offset in range(0, frame_count * frame_bytes, frame_bytes):
            frame = np.frombuffer(
                stdout[offset: offset + frame_bytes], dtype=np.uint8
            ).reshape(height, width, 3).astype(np.float32)
            distance = np.linalg.norm(frame - bg, axis=2)
            foreground = distance > 35.0
            occupancies.append(float(foreground.mean()))

            luma = 0.2126 * frame[:, :, 0] + 0.7152 * frame[:, :, 1] + 0.0722 * frame[:, :, 2]
            gx = np.zeros_like(luma)
            gy = np.zeros_like(luma)
            gx[:, 1:] = np.abs(luma[:, 1:] - luma[:, :-1])
            gy[1:, :] = np.abs(luma[1:, :] - luma[:-1, :])
            gradient = np.maximum(gx, gy)
            readable_edges = foreground & (gradient > 12.0)
            edge_ratio.append(float(readable_edges.mean()))
            if readable_edges.any():
                edge_luma.append(float(np.median(luma[readable_edges])))

        arr = np.asarray(occupancies, dtype=np.float32)
        edge_arr = np.asarray(edge_ratio, dtype=np.float32)
        return {
            "frame_count": float(frame_count),
            "empty_ratio": float(np.mean(arr < 0.003)),
            "p10_occupancy": float(np.percentile(arr, 10)),
            "p25_occupancy": float(np.percentile(arr, 25)),
            "median_occupancy": float(np.median(arr)),
            "edge_luma": float(np.median(edge_luma)) if edge_luma else 0.0,
            "p10_edge_ratio": float(np.percentile(edge_arr, 10)),
        }

    @staticmethod
    def _study_visual_limits() -> dict[str, float]:
        return {
            "max_empty": float(os.getenv("STUDY_MAX_EMPTY_FRAME_RATIO", "0.03")),
            "min_p10": float(os.getenv("STUDY_MIN_P10_OCCUPANCY", "0.015")),
            "min_p25": float(os.getenv("STUDY_MIN_P25_OCCUPANCY", "0.030")),
            "min_median": float(os.getenv("STUDY_MIN_MEDIAN_OCCUPANCY", "0.070")),
            # Median luma of readable high-contrast edges, not panel fills.
            "min_edge_luma": float(os.getenv("STUDY_MIN_EDGE_LUMA", os.getenv("STUDY_MIN_FOREGROUND_LUMA", "50"))),
            "min_edge_ratio": float(os.getenv("STUDY_MIN_P10_EDGE_RATIO", "0.003")),
        }

    @staticmethod
    def _study_visual_spatial_pass(metrics: dict[str, float], limits: dict[str, float]) -> bool:
        return (
            metrics["empty_ratio"] <= limits["max_empty"]
            and metrics["p10_occupancy"] >= limits["min_p10"]
            and metrics["p25_occupancy"] >= limits["min_p25"]
            and metrics["median_occupancy"] >= limits["min_median"]
        )

    @staticmethod
    def _study_visual_contrast_pass(metrics: dict[str, float], limits: dict[str, float]) -> bool:
        return (
            metrics["edge_luma"] >= limits["min_edge_luma"]
            and metrics["p10_edge_ratio"] >= limits["min_edge_ratio"]
        )

    @staticmethod
    def _print_study_visual_qc(
        metrics: dict[str, float], limits: dict[str, float], *, repaired: bool = False
    ) -> None:
        passed = (
            LocalVideoAssembler._study_visual_spatial_pass(metrics, limits)
            and LocalVideoAssembler._study_visual_contrast_pass(metrics, limits)
        )
        print(
            "[STUDY VISUAL QC] "
            f"empty={metrics['empty_ratio']:.1%}/{limits['max_empty']:.1%} "
            f"p10_occ={metrics['p10_occupancy']:.3f}/{limits['min_p10']:.3f} "
            f"p25_occ={metrics['p25_occupancy']:.3f}/{limits['min_p25']:.3f} "
            f"median_occ={metrics['median_occupancy']:.3f}/{limits['min_median']:.3f} "
            f"edge_luma={metrics['edge_luma']:.1f}/{limits['min_edge_luma']:.1f} "
            f"edge_p10={metrics['p10_edge_ratio']:.3f}/{limits['min_edge_ratio']:.3f} "
            f"repaired={'YES' if repaired else 'NO'} qc={'PASS' if passed else 'FAIL'}"
        )

    async def _repair_study_visual_contrast(self, output: Path) -> None:
        """Brighten diagram/text contrast without touching already-mastered audio.

        This is intentionally bounded: it cannot rescue empty/sparse composition.
        It only repairs a dark-theme render whose spatial metrics already pass.
        """
        filter_chain = os.getenv(
            "STUDY_VISUAL_CONTRAST_FILTER",
            "eq=contrast=1.08:brightness=0.018:saturation=1.05:gamma=1.03",
        ).strip()
        if not filter_chain:
            return
        temp = output.with_name(output.stem + ".contrast-repaired" + output.suffix)
        await self._run([
            self._ffmpeg_path, "-y", "-loglevel", "error", "-i", str(output),
            "-map", "0:v:0", "-map", "0:a?",
            "-vf", filter_chain,
            "-c:v", "libx264", "-preset", os.getenv("CONTENT_FACTORY_FFMPEG_PRESET", "fast"),
            "-crf", "17", "-profile:v", "high", "-level:v", "4.1",
            "-pix_fmt", "yuv420p", "-colorspace", "bt709",
            "-color_primaries", "bt709", "-color_trc", "bt709",
            "-c:a", "copy", "-movflags", "+faststart", str(temp),
        ])
        if not temp.is_file() or temp.stat().st_size < 1024:
            raise RuntimeError("Study visual contrast repair did not produce a valid file")
        temp.replace(output)

    async def _validate_study_visual_readability(self, output: Path) -> None:
        """Validate real rendered frames and self-heal contrast-only failures.

        Empty/sparse composition remains a hard blocker. Contrast-only failures
        receive one deterministic post-render repair, then are re-measured.
        """
        limits = self._study_visual_limits()
        metrics = await self._study_visual_metrics(output)
        spatial_ok = self._study_visual_spatial_pass(metrics, limits)
        contrast_ok = self._study_visual_contrast_pass(metrics, limits)
        self._print_study_visual_qc(metrics, limits, repaired=False)

        if not spatial_ok:
            raise RuntimeError(
                "Study visual readability QC failed: final render contains too many "
                "empty/sparse frames for mobile-first educational viewing."
            )
        if contrast_ok:
            return

        print(
            "[STUDY VISUAL REPAIR] contrast-only failure detected; "
            "applying bounded final-video readability repair"
        )
        await self._repair_study_visual_contrast(output)
        repaired = await self._study_visual_metrics(output)
        self._print_study_visual_qc(repaired, limits, repaired=True)
        if not self._study_visual_contrast_pass(repaired, limits):
            raise RuntimeError(
                "Study visual readability QC failed after automatic contrast repair: "
                "text/diagram edges remain too dim for mobile viewing."
            )

    async def _measure_loudness(self, media: Path, prefilter: str = "") -> dict[str, float]:
        """Measure integrated loudness/true peak using FFmpeg loudnorm."""
        target = float(os.getenv("STUDY_AUDIO_TARGET_LUFS", "-16.0"))
        peak = float(os.getenv("STUDY_AUDIO_TRUE_PEAK_DBTP", "-1.5"))
        command = [
            self._ffmpeg_path, "-nostdin", "-hide_banner", "-nostats", "-i", str(media),
            "-vn", "-af", (prefilter + "," if prefilter else "") + f"loudnorm=I={target}:TP={peak}:LRA=11:print_format=json",
            "-f", "null", "-",
        ]
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        text = stderr.decode("utf-8", errors="replace")
        if process.returncode != 0:
            raise RuntimeError("FFmpeg loudness analysis failed:\n" + text[-1200:])
        matches = re.findall(r"\{\s*\"input_i\".*?\}", text, flags=re.S)
        if not matches:
            raise RuntimeError("Could not parse FFmpeg loudness analysis output")
        data = json.loads(matches[-1])
        def number(key: str) -> float:
            value = str(data.get(key, "nan")).replace("-inf", "-99").replace("inf", "99")
            return float(value)
        return {
            "input_i": number("input_i"),
            "input_tp": number("input_tp"),
            "input_lra": number("input_lra"),
            "input_thresh": number("input_thresh"),
            "target_offset": number("target_offset"),
        }

    async def _master_study_audio(self, output: Path) -> None:
        """Master final study narration to a consistent YouTube-friendly level.

        Scene WAVs are intentionally kept lossless/unmastered for renderer sync.
        Loudness is applied once to the final mix so every lesson has predictable
        volume without accumulating per-scene gain or compression artifacts.
        """
        if os.getenv("STUDY_AUDIO_MASTERING", "1").strip().lower() in {"0", "false", "no"}:
            print("[AUDIO MASTER] disabled by STUDY_AUDIO_MASTERING=0")
            return

        target = float(os.getenv("STUDY_AUDIO_TARGET_LUFS", "-16.0"))
        peak = float(os.getenv("STUDY_AUDIO_TRUE_PEAK_DBTP", "-1.5"))
        tolerance = max(0.5, float(os.getenv("STUDY_AUDIO_LUFS_TOLERANCE", "1.2")))
        before = await self._measure_loudness(output)
        temp = output.with_name(output.stem + ".mastered" + output.suffix)

        # Dialogue clarity chain: remove sub-bass, add a very small presence lift
        # around consonants, apply light compression, then normalize the final
        # master. This is intentionally subtle so Kokoro/Piper do not sound
        # radio-processed or fatiguing during long lessons.
        clarity = os.getenv(
            "STUDY_AUDIO_CLARITY_FILTER",
            "highpass=f=70,equalizer=f=3200:t=q:w=1.1:g=1.5,"
            "acompressor=threshold=0.125:ratio=2:attack=15:release=160:makeup=1.35",
        ).strip()
        # Measure the exact clarity chain that will be normalized. Reusing raw
        # measurements here would invalidate two-pass normalization.
        measured = await self._measure_loudness(output, prefilter=clarity)
        normalization = (
            f"loudnorm=I={target}:TP={peak}:LRA=11:"
            f"measured_I={measured['input_i']}:"
            f"measured_TP={measured['input_tp']}:"
            f"measured_LRA={measured['input_lra']}:"
            f"measured_thresh={measured['input_thresh']}:"
            f"offset={measured['target_offset']}:linear=true:print_format=summary"
        )
        analysis_filter = f"{clarity},{normalization}" if clarity else normalization
        await self._run([
            self._ffmpeg_path, "-y", "-loglevel", "error", "-i", str(output),
            "-map", "0:v:0", "-map", "0:a?", "-c:v", "copy",
            "-af", analysis_filter,
            "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", str(temp),
        ])
        if not temp.is_file() or temp.stat().st_size < 1024:
            raise RuntimeError("Study audio mastering did not produce a valid file")
        temp.replace(output)

        after = await self._measure_loudness(output)
        loudness_ok = abs(after["input_i"] - target) <= tolerance
        peak_ok = after["input_tp"] <= peak + 0.35
        print(
            "[AUDIO MASTER] "
            f"before={before['input_i']:.1f}LUFS/{before['input_tp']:.1f}dBTP "
            f"after={after['input_i']:.1f}LUFS/{after['input_tp']:.1f}dBTP "
            f"target={target:.1f}LUFS/{peak:.1f}dBTP "
            f"qc={'PASS' if loudness_ok and peak_ok else 'FAIL'}"
        )
        if not loudness_ok or not peak_ok:
            raise RuntimeError(
                "Study audio loudness QC failed: "
                f"measured {after['input_i']:.1f} LUFS / {after['input_tp']:.1f} dBTP; "
                f"target {target:.1f}±{tolerance:.1f} LUFS and <= {peak:.1f} dBTP"
            )

    async def _concat(
        self,
        segments: list[Path],
        output: Path,
    ) -> None:
        concat_file = (
            output.parent
            / (".concat-" + uuid4().hex + ".txt")
        )

        concat_file.write_text(
            "\n".join(
                "file '" + str(segment.resolve()).replace("'", "'\\''") + "'"
                for segment in segments
            ),
            encoding="utf-8",
        )

        try:
            await self._run(
                [
                    self._ffmpeg_path,
                    "-y",
                    "-loglevel",
                    "error",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(
                        concat_file
                    ),
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-af",
                    "aresample=async=1:first_pts=0",
                    "-movflags",
                    "+faststart",
                    str(
                        output
                    ),
                ]
            )
        finally:
            concat_file.unlink(
                missing_ok=True
            )

    @staticmethod
    def _audio_duration(
        path: str,
    ) -> float:
        with wave.open(
            path,
            "rb",
        ) as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate()

        if rate <= 0:
            raise ValueError(
                f"Invalid WAV rate: {path}"
            )

        return (
            frames
            / rate
        )

    @staticmethod
    async def _run(
        command: list[str],
    ) -> None:
        command = [command[0], "-nostdin", "-threads", "2", *command[1:]]
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=3600)
        except (TimeoutError, asyncio.CancelledError):
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise

        if process.returncode != 0:
            raise RuntimeError(
                "FFmpeg command failed:\n"
                + stderr.decode(
                    "utf-8",
                    errors="replace",
                )
            )
