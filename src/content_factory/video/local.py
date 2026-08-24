from __future__ import annotations

import asyncio
import json
import os
import wave
from contextlib import suppress
from pathlib import Path

from content_factory.video.base import VideoAssembler


class LocalVideoAssembler(VideoAssembler):
    """
    1080p quality-first, motion-aware YouTube assembler.

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
                        "2",
                    )
                ),
            ),
        )

        print(
            "[VIDEO] V4 quality output: "
            "1080p30 / H.264 CRF17 / BT.709 / motion-aware."
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
            / ".segments"
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

        semaphore = asyncio.Semaphore(
            self._parallel_segments
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

            total = sum(
                self._audio_duration(
                    voice
                )
                for voice in voice_files
            )

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
            "medium",
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
                "medium",
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
                        "medium",
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
                    "-c",
                    "copy",
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

        if mode == "editorial_static":
            # Preserve typography. Very small push-in only.
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
                }:
                    return mode
            except Exception:
                pass

        return "creative_push"

    async def _concat(
        self,
        segments: list[Path],
        output: Path,
    ) -> None:
        concat_file = (
            output.parent
            / ".concat.txt"
        )

        concat_file.write_text(
            "\n".join(
                f"file '{segment.resolve()}'"
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
                    "-c",
                    "copy",
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
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        _, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(
                "FFmpeg command failed:\n"
                + stderr.decode(
                    "utf-8",
                    errors="replace",
                )
            )
