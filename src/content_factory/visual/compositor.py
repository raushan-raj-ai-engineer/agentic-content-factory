from __future__ import annotations

import re
from pathlib import Path

from PIL import (
    Image,
    ImageDraw,
    ImageEnhance,
    ImageFilter,
    ImageFont,
    ImageOps,
)


class PremiumSceneCompositor:
    WIDTH = 1920
    HEIGHT = 1080

    def compose_public_photo(
        self,
        *,
        image_path: str | Path,
        title: str,
        summary: str,
        domain: str,
        scene_index: int,
        show_overlay: bool | None = None,
    ) -> None:
        path = Path(
            image_path
        )

        if show_overlay is None:
            show_overlay = scene_index in {
                1,
                10,
            }

        with Image.open(
            path
        ) as source:
            image = source.convert(
                "RGB"
            )

        image = ImageOps.fit(
            image,
            (
                self.WIDTH,
                self.HEIGHT,
            ),
            method=Image.Resampling.LANCZOS,
            centering=self._centering(
                scene_index
            ),
        )

        image = ImageEnhance.Contrast(
            image
        ).enhance(
            1.03
        )
        image = ImageEnhance.Color(
            image
        ).enhance(
            1.02
        )

        overlay = Image.new(
            "RGBA",
            image.size,
            (
                0,
                0,
                0,
                0,
            ),
        )
        draw_overlay = ImageDraw.Draw(
            overlay
        )

        if show_overlay:
            for y in range(
                self.HEIGHT
            ):
                normalized = (
                    y
                    / max(
                        1,
                        self.HEIGHT - 1,
                    )
                )

                alpha = int(
                    max(
                        0.0,
                        (
                            normalized
                            - 0.68
                        )
                        / 0.32,
                    )
                    * 150
                )

                if alpha > 0:
                    draw_overlay.line(
                        (
                            0,
                            y,
                            self.WIDTH,
                            y,
                        ),
                        fill=(
                            5,
                            7,
                            12,
                            alpha,
                        ),
                    )

        image = Image.alpha_composite(
            image.convert(
                "RGBA"
            ),
            overlay,
        )

        draw = ImageDraw.Draw(
            image
        )

        if show_overlay:
            label = {
                "sports": "SPORT",
                "legal": "CONTEXT",
                "finance": "MARKET",
                "news": "UPDATE",
                "education": "EDUCATION",
                "travel": "PLACE",
                "entertainment": "ENTERTAINMENT",
                "automotive": "AUTO",
                "science": "SCIENCE",
                "environment": "ENVIRONMENT",
                "food": "FOOD",
                "history_culture": "HISTORY",
                "religion_spirituality": "CULTURE",
                "agriculture": "AGRICULTURE",
                "business": "BUSINESS",
                "politics": "POLITICS",
                "career": "CAREER",
                "public_service": "PUBLIC SERVICE",
                "health": "HEALTH",
                "crime_safety": "SAFETY",
                "product": "PRODUCT",
            }.get(
                domain,
                "CONTEXT",
            )

            chip_font = self._font(
                20,
                bold=True,
            )
            chip_box = draw.textbbox(
                (
                    0,
                    0,
                ),
                label,
                font=chip_font,
            )
            chip_width = (
                chip_box[
                    2
                ]
                - chip_box[
                    0
                ]
                + 52
            )

            draw.rounded_rectangle(
                (
                    64,
                    54,
                    64
                    + chip_width,
                    108,
                ),
                radius=18,
                fill=(
                    8,
                    10,
                    15,
                    170,
                ),
            )

            draw.text(
                (
                    90,
                    70,
                ),
                label,
                font=chip_font,
                fill=(
                    248,
                    249,
                    252,
                    245,
                ),
            )

            # Only opening/outro primary shots carry a minimal overlay.
            clean_title = self._short(
                title,
                58,
            )

            font = self._fit_font(
                draw,
                clean_title,
                max_width=1420,
                max_size=54,
                min_size=38,
                max_lines=2,
            )

            self._draw_wrapped(
                draw,
                clean_title,
                (
                    82,
                    875,
                ),
                font,
                max_width=1420,
                max_lines=2,
                fill=(
                    251,
                    252,
                    254,
                    255,
                ),
            )

        image.convert(
            "RGB"
        ).save(
            path,
            format="PNG",
            optimize=True,
        )

    @staticmethod
    def _centering(
        scene_index: int,
    ) -> tuple[
        float,
        float,
    ]:
        variants = (
            (
                0.50,
                0.48,
            ),
            (
                0.44,
                0.50,
            ),
            (
                0.56,
                0.50,
            ),
        )

        return variants[
            scene_index
            % len(
                variants
            )
        ]

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

        if len(
            clean
        ) <= limit:
            return clean

        return (
            clean[
                : limit - 1
            ].rstrip()
            + "…"
        )

    @classmethod
    def _fit_font(
        cls,
        draw: ImageDraw.ImageDraw,
        text: str,
        *,
        max_width: int,
        max_size: int,
        min_size: int,
        max_lines: int,
    ) -> ImageFont.ImageFont:
        for size in range(
            max_size,
            min_size - 1,
            -2,
        ):
            font = cls._font(
                size,
                bold=True,
            )

            if len(
                cls._wrap(
                    draw,
                    text,
                    font,
                    max_width,
                )
            ) <= max_lines:
                return font

        return cls._font(
            min_size,
            bold=True,
        )

    @classmethod
    def _draw_wrapped(
        cls,
        draw: ImageDraw.ImageDraw,
        text: str,
        xy: tuple[
            int,
            int,
        ],
        font: ImageFont.ImageFont,
        *,
        max_width: int,
        max_lines: int,
        fill: tuple[
            int,
            int,
            int,
            int,
        ],
    ) -> None:
        lines = cls._wrap(
            draw,
            text,
            font,
            max_width,
        )[
            :max_lines
        ]

        x, y = xy

        for line in lines:
            draw.text(
                (
                    x,
                    y,
                ),
                line,
                font=font,
                fill=fill,
                stroke_width=2,
                stroke_fill=(
                    0,
                    0,
                    0,
                    145,
                ),
            )

            box = draw.textbbox(
                (
                    x,
                    y,
                ),
                line,
                font=font,
                stroke_width=2,
            )

            y += (
                box[3]
                - box[1]
                + 10
            )

    @staticmethod
    def _wrap(
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.ImageFont,
        max_width: int,
    ) -> list[str]:
        words = text.split()
        lines: list[str] = []
        current: list[str] = []

        for word in words:
            candidate = " ".join(
                current
                + [
                    word
                ]
            )

            box = draw.textbbox(
                (
                    0,
                    0,
                ),
                candidate,
                font=font,
            )

            if (
                box[2]
                - box[0]
            ) <= max_width:
                current.append(
                    word
                )
            else:
                if current:
                    lines.append(
                        " ".join(
                            current
                        )
                    )
                current = [
                    word
                ]

        if current:
            lines.append(
                " ".join(
                    current
                )
            )

        return lines

    @staticmethod
    def _font(
        size: int,
        *,
        bold: bool,
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
            if not Path(
                candidate
            ).exists():
                continue

            try:
                return ImageFont.truetype(
                    candidate,
                    size=size,
                )
            except OSError:
                continue

        return ImageFont.load_default()
