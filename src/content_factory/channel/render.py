from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from content_factory.local_video.media import concat_media, duration_seconds, run

VERSION = "channel-render-sme-v2"
WIDTH = 1920
HEIGHT = 1080
FPS = 24


def font(size: int, mono: bool = False):
    paths = (
        [
            "/System/Library/Fonts/Menlo.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "C:/Windows/Fonts/consola.ttf",
        ]
        if mono
        else [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]
    )
    for path in paths:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def _fit_text(draw: ImageDraw.ImageDraw, text: str, max_width: int, start: int, minimum: int, *, mono: bool = False):
    size = start
    selected = font(size, mono)
    while draw.textlength(text, font=selected) > max_width and size > minimum:
        size -= 2
        selected = font(size, mono)
    return selected


def _cell_positions(count: int) -> list[tuple[int, int]]:
    if count <= 7:
        cell_w = 220
        gap = 28
        total = count * cell_w + max(0, count - 1) * gap
        start_x = (WIDTH - total) // 2
        return [(start_x + i * (cell_w + gap), 330) for i in range(count)]
    cols = 6
    cell_w = 220
    gap = 28
    total = cols * cell_w + (cols - 1) * gap
    start_x = (WIDTH - total) // 2
    return [
        (start_x + (i % cols) * (cell_w + gap), 290 + (i // cols) * 210)
        for i in range(count)
    ]


def card(spec: dict, path: Path, reveal: int = 2) -> None:
    """Render one 1080p teaching card.

    reveal=0: establish context
    reveal=1: reveal pointers/highlights/eliminated state
    reveal=2: reveal explanation/comparison/callout
    """
    im = Image.new("RGB", (WIDTH, HEIGHT), "#08111F")
    draw = ImageDraw.Draw(im)

    # Teaching identity and stage indicator.
    draw.text((70, 42), "CODE  →  UNDERSTAND  →  VERIFY", font=font(27), fill="#5EEAD4")
    stage = str(spec.get("stage") or "explain").replace("-", " ").upper()
    stage_font = font(23)
    stage_w = int(draw.textlength(stage, font=stage_font)) + 48
    draw.rounded_rectangle((WIDTH - stage_w - 70, 38, WIDTH - 70, 86), 16, fill="#132238")
    draw.text((WIDTH - stage_w - 46, 50), stage, font=stage_font, fill="#C4B5FD")

    title_font = _fit_text(draw, str(spec["title"]), 1700, 58, 34)
    draw.text((70, 115), str(spec["title"]), font=title_font, fill="white")

    goal = str(spec.get("learning_goal") or "").strip()
    if goal:
        goal_text = textwrap.shorten(goal, width=130, placeholder="…")
        draw.text((72, 202), goal_text, font=font(25), fill="#94A3B8")

    if spec.get("code"):
        code_lines = str(spec["code"]).splitlines()
        top = 285
        line_h = min(58, max(38, int(620 / max(1, len(code_lines)))))
        code_font = font(max(27, line_h - 12), True)
        draw.rounded_rectangle((70, top - 28, WIDTH - 70, 925), 22, fill="#0E1B2D", outline="#334155", width=3)
        for i, line in enumerate(code_lines):
            y = top + i * line_h
            prefix = f"{i + 1:>2}  "
            draw.text((100, y), prefix, font=code_font, fill="#64748B")
            draw.text((175, y), line, font=code_font, fill="#DBEAFE")
        if reveal >= 2 and spec.get("callout"):
            text_value = str(spec["callout"])
            f = _fit_text(draw, text_value, 1500, 30, 22)
            draw.rounded_rectangle((250, 942, WIDTH - 250, 1005), 18, fill="#12352F", outline="#2DD4BF", width=2)
            tw = draw.textlength(text_value, font=f)
            draw.text(((WIDTH - tw) / 2, 958), text_value, font=f, fill="#CCFBF1")
    else:
        values = list(spec.get("values", []))
        positions = _cell_positions(len(values))
        inactive = set(spec.get("inactive", [])) if reveal >= 1 else set()
        active = set(spec.get("active", [])) if reveal >= 1 else set()
        pointers = dict(spec.get("pointers", {})) if reveal >= 1 else {}

        for i, value in enumerate(values):
            x, y = positions[i]
            w, h = 220, 112
            is_inactive = i in inactive
            is_active = i in active
            fill = "#0F2D2A" if is_active else ("#111827" if is_inactive else "#17243A")
            outline = "#5EEAD4" if is_active else ("#334155" if is_inactive else "#64748B")
            draw.rounded_rectangle((x, y, x + w, y + h), 18, fill=fill, outline=outline, width=4 if is_active else 2)
            label = repr(value) if value == " " else value
            vf = _fit_text(draw, label, w - 36, 43, 25)
            bbox = draw.textbbox((0, 0), label, font=vf)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            value_fill = "#64748B" if is_inactive else "white"
            draw.text((x + (w - tw) / 2, y + 25), label, font=vf, fill=value_fill)
            draw.text((x + w / 2 - 10, y + h + 15), str(i), font=font(24), fill="#64748B")
            if is_inactive:
                draw.line((x + 24, y + 20, x + w - 24, y + h - 20), fill="#475569", width=5)
                draw.line((x + w - 24, y + 20, x + 24, y + h - 20), fill="#475569", width=5)

        if reveal >= 1:
            pointer_groups: dict[int, list[str]] = {}
            for name, idx in pointers.items():
                if isinstance(idx, int) and 0 <= idx < len(positions):
                    pointer_groups.setdefault(idx, []).append(str(name))
            for idx, names in pointer_groups.items():
                x, y = positions[idx]
                label = "/".join(names)
                pf = _fit_text(draw, label, 210, 23, 17, mono=True)
                tw = draw.textlength(label, font=pf)
                draw.polygon([(x + 110, y - 10), (x + 96, y - 34), (x + 124, y - 34)], fill="#FBBF24")
                draw.text((x + 110 - tw / 2, y - 68), label, font=pf, fill="#FDE68A")

        if reveal >= 2:
            detail = str(spec.get("detail") or "").strip()
            comparison = str(spec.get("comparison") or "").strip()
            callout = str(spec.get("callout") or "").strip()
            base_y = 690 if len(values) <= 7 else 745

            if comparison:
                comp_font = _fit_text(draw, comparison, 1150, 42, 25, mono=True)
                comp_w = draw.textlength(comparison, font=comp_font)
                box_w = min(1300, max(440, int(comp_w) + 100))
                x1 = (WIDTH - box_w) // 2
                draw.rounded_rectangle((x1, base_y, x1 + box_w, base_y + 82), 20, fill="#271B36", outline="#A78BFA", width=2)
                draw.text(((WIDTH - comp_w) / 2, base_y + 20), comparison, font=comp_font, fill="#EDE9FE")
                base_y += 105

            if detail:
                detail_lines: list[str] = []
                for raw in detail.splitlines():
                    detail_lines.extend(textwrap.wrap(raw, width=88) or [""])
                for line in detail_lines[:3]:
                    df = _fit_text(draw, line, 1640, 31, 22, mono=True)
                    tw = draw.textlength(line, font=df)
                    draw.text(((WIDTH - tw) / 2, base_y), line, font=df, fill="#DBEAFE")
                    base_y += 43

            if callout:
                cf = _fit_text(draw, callout, 1500, 31, 22)
                tw = draw.textlength(callout, font=cf)
                y = min(base_y + 8, 938)
                draw.rounded_rectangle((220, y, WIDTH - 220, y + 64), 18, fill="#12352F", outline="#2DD4BF", width=2)
                draw.text(((WIDTH - tw) / 2, y + 15), callout, font=cf, fill="#CCFBF1")

    footer = f"{spec.get('index', 0) + 1:02d} / {spec.get('total', 1):02d}   •   SME study lesson   •   1080p"
    draw.text((72, 1030), footer, font=font(23), fill="#64748B")
    im.save(path)


def _render_card_phases(spec: dict, work: Path, out: Path) -> None:
    seconds = float(spec["seconds"])
    # Progressive reveal makes the lightweight renderer useful for teaching:
    # establish → inspect state → explain decision/result.
    levels = [0, 1, 2]
    weights = [0.22, 0.31, 0.47]
    parts: list[Path] = []
    for idx, (level, weight) in enumerate(zip(levels, weights, strict=True)):
        frame = work / f"frame_{idx}.png"
        card(spec, frame, reveal=level)
        part = work / f"phase_{idx}.mp4"
        duration = max(0.35, seconds * weight)
        run(
            [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-framerate",
                str(FPS),
                "-i",
                str(frame),
                "-t",
                f"{duration:.4f}",
                # Do not fade each teaching phase to black. The phases are
                # incremental versions of the same card; a direct cut makes
                # labels/highlights appear naturally without a visible flash.
                "-vf",
                f"fps={FPS},format=yuv420p",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "19",
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(FPS),
                "-threads",
                "2",
                str(part),
            ]
        )
        parts.append(part)
    concat_media(parts, out, reencode=True)


def render(spec: dict, work: Path, out: Path, renderer: str) -> None:
    work.mkdir(parents=True, exist_ok=True)
    if renderer == "cards":
        _render_card_phases(spec, work, out)
    else:
        data = work / "scene.json"
        data.write_text(json.dumps(spec), encoding="utf-8")
        env = os.environ.copy()
        env["CHANNEL_SCENE"] = str(data.resolve())
        subprocess.run(
            [
                sys.executable,
                "-m",
                "manim",
                "render",
                "--renderer",
                "cairo",
                "--resolution",
                f"{WIDTH},{HEIGHT}",
                "--fps",
                str(FPS),
                "--disable_caching",
                "--media_dir",
                str((work / "manim").resolve()),
                "-o",
                "scene.mp4",
                str(Path(__file__).with_name("manim_scene.py")),
                "ChannelScene",
            ],
            env=env,
            check=True,
            stdin=subprocess.DEVNULL,
            timeout=1800,
        )
        matches = list((work / "manim").rglob("scene.mp4"))
        if len(matches) != 1:
            raise RuntimeError("Manim did not produce one scene.mp4")
        import shutil

        shutil.copy2(matches[0], out)
    if abs(duration_seconds(out) - float(spec["seconds"])) > 0.35:
        raise RuntimeError("Scene render duration mismatch")
