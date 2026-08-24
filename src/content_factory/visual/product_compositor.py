from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont


class ProductSceneCompositor:
    WIDTH = 1920
    HEIGHT = 1080

    def compose(
        self,
        *,
        image_path: str | Path,
        title: str,
        description: str,
        visual_type: str,
    ) -> None:
        path = Path(image_path)

        with Image.open(path) as source:
            image = source.convert("RGB")

        image = ImageEnhance.Contrast(
            image
        ).enhance(1.05)

        overlay = Image.new(
            "RGBA",
            image.size,
            (0, 0, 0, 0),
        )
        draw_overlay = ImageDraw.Draw(
            overlay
        )

        # Bottom cinematic gradient only. Product art remains dominant.
        for y in range(self.HEIGHT):
            t = y / max(1, self.HEIGHT - 1)
            alpha = int(
                max(
                    0.0,
                    (t - 0.62) / 0.38,
                )
                * 185
            )
            if alpha:
                draw_overlay.line(
                    (0, y, self.WIDTH, y),
                    fill=(5, 7, 12, alpha),
                )

        image = Image.alpha_composite(
            image.convert("RGBA"),
            overlay,
        )
        draw = ImageDraw.Draw(image)

        label = self._label(
            visual_type
        )

        draw.rounded_rectangle(
            (86, 65, 440, 132),
            radius=24,
            fill=(7, 9, 15, 205),
        )
        draw.text(
            (115, 84),
            label,
            font=self._font(24),
            fill=(247, 249, 253, 255),
        )

        # Small feature metric, only when explicitly present in narration.
        metric = self._metric(
            description
        )

        if metric:
            metric_font = self._font(
                54,
                bold=True,
            )
            box = draw.textbbox(
                (0, 0),
                metric,
                font=metric_font,
            )
            width = (
                box[2]
                - box[0]
                + 70
            )

            draw.rounded_rectangle(
                (
                    self.WIDTH
                    - width
                    - 80,
                    70,
                    self.WIDTH
                    - 80,
                    165,
                ),
                radius=30,
                fill=(245, 247, 251, 235),
            )
            draw.text(
                (
                    self.WIDTH
                    - width
                    - 45,
                    88,
                ),
                metric,
                font=metric_font,
                fill=(15, 18, 24, 255),
            )

        clean_title = self._short(
            title,
            76,
        )

        draw.text(
            (95, 880),
            clean_title,
            font=self._font(
                50,
                bold=True,
            ),
            fill=(250, 251, 254, 255),
            stroke_width=2,
            stroke_fill=(0, 0, 0, 150),
        )

        image.convert("RGB").save(
            path,
            format="PNG",
            optimize=True,
        )

    @staticmethod
    def _label(
        visual_type: str,
    ) -> str:
        value = visual_type.lower()

        if "hero" in value:
            return "PRODUCT FOCUS"
        if "macro" in value:
            return "DESIGN DETAIL"
        if "audio" in value:
            return "SOUND & ANC"
        if "battery" in value:
            return "BATTERY"
        if "gaming" in value:
            return "GAMING"
        if "app" in value:
            return "APP & CONTROLS"
        if "value" in value:
            return "VALUE"
        if "verdict" in value:
            return "VERDICT"
        if "lifestyle" in value:
            return "EVERYDAY USE"

        return "KEY FEATURE"

    @staticmethod
    def _metric(
        text: str,
    ) -> str | None:
        patterns = (
            r"₹\s?\d[\d,]*(?:\.\d+)?",
            r"\b\d+(?:\.\d+)?\s?(?:dB|db)\b",
            r"\b\d+(?:\.\d+)?\s?(?:mm|ms)\b",
            r"\b\d+(?:\.\d+)?\s?(?:hours?|hrs?|h)\b",
            r"\bBluetooth\s+\d+(?:\.\d+)?\b",
            r"\bIP\d{2}\b",
        )

        for pattern in patterns:
            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )
            if match:
                return re.sub(
                    r"\s+",
                    " ",
                    match.group(0),
                ).strip()

        return None

    @staticmethod
    def _short(
        text: str,
        limit: int,
    ) -> str:
        clean = re.sub(
            r"\s+",
            " ",
            text or "",
        ).strip()

        if len(clean) <= limit:
            return clean

        return (
            clean[: limit - 1].rstrip()
            + "…"
        )

    @staticmethod
    def _font(
        size: int,
        *,
        bold: bool = False,
    ) -> ImageFont.ImageFont:
        candidates = []

        if bold:
            candidates.extend(
                [
                    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                    "/System/Library/Fonts/Supplemental/Helvetica Bold.ttf",
                ]
            )

        candidates.extend(
            [
                "/System/Library/Fonts/Supplemental/Arial.ttf",
                "/System/Library/Fonts/Helvetica.ttc",
            ]
        )

        for candidate in candidates:
            if not Path(candidate).exists():
                continue

            try:
                return ImageFont.truetype(
                    candidate,
                    size=size,
                )
            except OSError:
                pass

        return ImageFont.load_default()
