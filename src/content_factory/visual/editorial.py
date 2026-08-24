from __future__ import annotations

import hashlib
import re
from pathlib import Path

from PIL import (
    Image,
    ImageDraw,
    ImageFont,
)

from content_factory.visual.semantic_router import (
    extract_matchup,
)


class ViewerGraphicRenderer:
    """
    1080p factual/editorial renderer.

    The goal is not decorative slides. Each frame must communicate ONE clear
    idea immediately, using only text derived from the supplied scene.
    """

    WIDTH = 1920
    HEIGHT = 1080

    BG = (15, 18, 26)
    PANEL = (31, 37, 50)
    PANEL_ALT = (42, 49, 65)
    TEXT = (247, 248, 251)
    MUTED = (190, 198, 214)
    ACCENT = (230, 236, 250)
    LINE = (109, 122, 150)

    def render(
        self,
        *,
        title: str,
        description: str,
        visual_type: str,
        output_path: str,
        prompt: str = "",
    ) -> None:
        path = Path(
            output_path
        )
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        image = Image.new(
            "RGB",
            (
                self.WIDTH,
                self.HEIGHT,
            ),
            self.BG,
        )
        draw = ImageDraw.Draw(
            image
        )

        vtype = (
            visual_type
            or "editorial"
        ).lower()

        combined = (
            f"{title} {description} {prompt}"
        )

        if "education" in vtype:
            self._education(
                draw,
                title,
                description,
            )
        elif "sports" in vtype:
            self._sports(
                draw,
                title,
                description,
                combined,
            )
        elif "legal" in vtype:
            self._legal(
                draw,
                title,
                description,
            )
        elif "finance" in vtype:
            self._finance(
                draw,
                title,
                description,
            )
        elif "timeline" in vtype:
            self._timeline(
                draw,
                title,
                description,
            )
        elif "comparison" in vtype:
            self._comparison(
                draw,
                title,
                description,
                combined,
            )
        elif "outro" in vtype:
            self._outro(
                draw,
                title,
            )
        elif "news" in vtype:
            self._news(
                draw,
                title,
                description,
            )
        elif (
            "infographic"
            in vtype
        ):
            self._infographic(
                draw,
                title,
                description,
            )
        else:
            self._editorial(
                draw,
                title,
                description,
            )

        image.save(
            path,
            format="PNG",
            optimize=True,
        )

    def _education(
        self,
        draw: ImageDraw.ImageDraw,
        title: str,
        description: str,
    ) -> None:
        self._top_label(
            draw,
            "SCHOLARSHIP GUIDE",
        )

        self._headline_block(
            draw,
            title,
            top=175,
            max_size=78,
        )

        draw.rounded_rectangle(
            (
                115,
                560,
                620,
                900,
            ),
            radius=36,
            fill=self.PANEL,
        )

        draw.rounded_rectangle(
            (
                205,
                610,
                530,
                845,
            ),
            radius=18,
            outline=self.LINE,
            width=4,
        )

        for y in (
            670,
            730,
            790,
        ):
            draw.line(
                (
                    260,
                    y,
                    475,
                    y,
                ),
                fill=self.MUTED,
                width=5,
            )

        draw.line(
            (
                675,
                730,
                925,
                730,
            ),
            fill=self.TEXT,
            width=8,
        )

        draw.polygon(
            [
                (
                    925,
                    700,
                ),
                (
                    985,
                    730,
                ),
                (
                    925,
                    760,
                ),
            ],
            fill=self.TEXT,
        )

        draw.rounded_rectangle(
            (
                1030,
                560,
                1805,
                900,
            ),
            radius=36,
            fill=self.PANEL_ALT,
        )

        self._center_text(
            draw,
            self._short(
                description,
                150,
            ),
            (
                1090,
                610,
                1745,
                850,
            ),
            self._font(
                34,
                bold=True,
            ),
            max_lines=4,
        )

    def _sports(
        self,
        draw: ImageDraw.ImageDraw,
        title: str,
        description: str,
        combined: str,
    ) -> None:
        matchup = extract_matchup(
            title,
            combined,
        )

        self._top_label(
            draw,
            "MATCH CONTEXT",
        )

        if matchup:
            left, right = matchup

            self._panel(
                draw,
                (
                    95,
                    230,
                    835,
                    720,
                ),
            )
            self._panel(
                draw,
                (
                    1085,
                    230,
                    1825,
                    720,
                ),
            )

            self._center_text(
                draw,
                left,
                (
                    130,
                    340,
                    800,
                    620,
                ),
                self._font(
                    74,
                    bold=True,
                ),
                max_lines=3,
            )

            self._center_text(
                draw,
                right,
                (
                    1120,
                    340,
                    1790,
                    620,
                ),
                self._font(
                    74,
                    bold=True,
                ),
                max_lines=3,
            )

            draw.ellipse(
                (
                    865,
                    375,
                    1055,
                    565,
                ),
                fill=self.TEXT,
            )
            self._center_text(
                draw,
                "VS",
                (
                    865,
                    375,
                    1055,
                    565,
                ),
                self._font(
                    62,
                    bold=True,
                ),
                fill=self.BG,
                max_lines=1,
            )
        else:
            self._headline_block(
                draw,
                title,
                top=260,
                max_size=88,
            )

        self._summary_bar(
            draw,
            description,
            top=810,
            label="WHAT THIS SCENE EXPLAINS",
        )

        # Simple pitch markings signal sports without pretending to show
        # a real match, score or team branding.
        draw.arc(
            (
                820,
                180,
                1100,
                460,
            ),
            start=0,
            end=180,
            fill=self.LINE,
            width=4,
        )
        draw.line(
            (
                960,
                170,
                960,
                760,
            ),
            fill=self.LINE,
            width=3,
        )

    def _legal(
        self,
        draw: ImageDraw.ImageDraw,
        title: str,
        description: str,
    ) -> None:
        self._top_label(
            draw,
            "LEGAL EXPLAINER",
        )

        self._headline_block(
            draw,
            title,
            top=165,
            max_size=76,
        )

        # Document/process metaphor only. No fake court seal, judgment text,
        # judge portrait or claim of an actual document screenshot.
        draw.rounded_rectangle(
            (
                145,
                515,
                760,
                900,
            ),
            radius=34,
            fill=self.PANEL,
        )

        draw.rounded_rectangle(
            (
                215,
                565,
                690,
                845,
            ),
            radius=18,
            outline=self.LINE,
            width=4,
        )

        for y in (
            625,
            690,
            755,
        ):
            draw.line(
                (
                    275,
                    y,
                    630,
                    y,
                ),
                fill=self.MUTED,
                width=5,
            )

        # Process arrow.
        draw.line(
            (
                805,
                705,
                1015,
                705,
            ),
            fill=self.TEXT,
            width=10,
        )
        draw.polygon(
            [
                (
                    1015,
                    675,
                ),
                (
                    1075,
                    705,
                ),
                (
                    1015,
                    735,
                ),
            ],
            fill=self.TEXT,
        )

        draw.rounded_rectangle(
            (
                1110,
                515,
                1775,
                900,
            ),
            radius=34,
            fill=self.PANEL_ALT,
        )

        self._center_text(
            draw,
            "WHAT THE PETITION\\nASKS THE COURT\\nTO REVIEW",
            (
                1170,
                570,
                1715,
                835,
            ),
            self._font(
                43,
                bold=True,
            ),
            max_lines=3,
        )

        self._summary_bar(
            draw,
            description,
            top=920,
            label="KEY POINT FROM THE NARRATION",
        )

    def _news(
        self,
        draw: ImageDraw.ImageDraw,
        title: str,
        description: str,
    ) -> None:
        self._top_label(
            draw,
            "KEY UPDATE",
        )
        self._headline_block(
            draw,
            title,
            top=220,
            max_size=92,
        )

        draw.rounded_rectangle(
            (
                110,
                650,
                1810,
                920,
            ),
            radius=36,
            fill=self.PANEL,
        )
        self._draw_wrapped(
            draw,
            self._short(
                description,
                230,
            ),
            (
                165,
                710,
            ),
            self._font(
                42,
            ),
            max_width=1540,
            max_lines=3,
            fill=self.TEXT,
        )

    def _finance(
        self,
        draw: ImageDraw.ImageDraw,
        title: str,
        description: str,
    ) -> None:
        self._top_label(
            draw,
            "MARKET CONTEXT",
        )
        self._headline_block(
            draw,
            title,
            top=185,
            max_size=78,
        )

        chart_box = (
            130,
            520,
            1790,
            830,
        )

        draw.rounded_rectangle(
            chart_box,
            radius=32,
            fill=self.PANEL,
        )

        digest = hashlib.sha256(
            (
                title
                + description
            ).encode(
                "utf-8"
            )
        ).digest()

        points = []
        x = 190
        baseline = 720

        for index in range(
            8
        ):
            offset = (
                digest[index]
                % 170
            )
            y = (
                baseline
                - offset
                - index * 14
            )
            points.append(
                (
                    x,
                    max(
                        560,
                        min(
                            790,
                            y,
                        ),
                    ),
                )
            )
            x += 220

        draw.line(
            points,
            fill=self.ACCENT,
            width=8,
            joint="curve",
        )

        for x, y in points:
            draw.ellipse(
                (
                    x - 10,
                    y - 10,
                    x + 10,
                    y + 10,
                ),
                fill=self.TEXT,
            )

        # No numeric axes: this is contextual, not fake market data.
        self._summary_bar(
            draw,
            description,
            top=880,
            label="KEY POINT",
        )

    def _timeline(
        self,
        draw: ImageDraw.ImageDraw,
        title: str,
        description: str,
    ) -> None:
        self._top_label(
            draw,
            "TIMELINE",
        )
        self._headline_block(
            draw,
            title,
            top=175,
            max_size=72,
        )

        items = self._clauses(
            description,
            3,
        )

        y = 675
        draw.line(
            (
                220,
                y,
                1700,
                y,
            ),
            fill=self.LINE,
            width=6,
        )

        xs = (
            300,
            960,
            1620,
        )

        for index, x in enumerate(
            xs
        ):
            draw.ellipse(
                (
                    x - 24,
                    y - 24,
                    x + 24,
                    y + 24,
                ),
                fill=self.TEXT,
            )

            label = (
                items[index]
                if index < len(
                    items
                )
                else (
                    "Next point"
                    if index == 2
                    else "Context"
                )
            )

            self._center_text(
                draw,
                label,
                (
                    x - 230,
                    735,
                    x + 230,
                    960,
                ),
                self._font(
                    30,
                ),
                max_lines=4,
            )

    def _comparison(
        self,
        draw: ImageDraw.ImageDraw,
        title: str,
        description: str,
        combined: str,
    ) -> None:
        self._top_label(
            draw,
            "COMPARISON",
        )
        self._headline_block(
            draw,
            title,
            top=170,
            max_size=70,
        )

        matchup = extract_matchup(
            title,
            combined,
        )

        if matchup:
            labels = matchup
        else:
            labels = (
                "SIDE A",
                "SIDE B",
            )

        clauses = self._clauses(
            description,
            2,
        )

        for index, (
            x1,
            x2,
        ) in enumerate(
            (
                (
                    100,
                    905,
                ),
                (
                    1015,
                    1820,
                ),
            )
        ):
            draw.rounded_rectangle(
                (
                    x1,
                    520,
                    x2,
                    930,
                ),
                radius=38,
                fill=(
                    self.PANEL
                    if index == 0
                    else self.PANEL_ALT
                ),
            )
            self._center_text(
                draw,
                labels[index],
                (
                    x1 + 70,
                    580,
                    x2 - 70,
                    700,
                ),
                self._font(
                    48,
                    bold=True,
                ),
                max_lines=2,
            )

            body = (
                clauses[index]
                if index < len(
                    clauses
                )
                else self._short(
                    description,
                    120,
                )
            )

            self._center_text(
                draw,
                body,
                (
                    x1 + 70,
                    730,
                    x2 - 70,
                    875,
                ),
                self._font(
                    30,
                ),
                max_lines=3,
            )

    def _infographic(
        self,
        draw: ImageDraw.ImageDraw,
        title: str,
        description: str,
    ) -> None:
        self._top_label(
            draw,
            "3 KEY POINTS",
        )
        self._headline_block(
            draw,
            title,
            top=170,
            max_size=70,
        )

        items = self._clauses(
            description,
            3,
        )

        for index in range(
            3
        ):
            x1 = (
                90
                + index * 610
            )
            x2 = x1 + 540

            draw.rounded_rectangle(
                (
                    x1,
                    520,
                    x2,
                    910,
                ),
                radius=36,
                fill=(
                    self.PANEL
                    if index % 2 == 0
                    else self.PANEL_ALT
                ),
            )

            draw.ellipse(
                (
                    x1 + 40,
                    560,
                    x1 + 110,
                    630,
                ),
                fill=self.TEXT,
            )

            self._center_text(
                draw,
                str(
                    index + 1
                ),
                (
                    x1 + 40,
                    560,
                    x1 + 110,
                    630,
                ),
                self._font(
                    30,
                    bold=True,
                ),
                fill=self.BG,
                max_lines=1,
            )

            body = (
                items[index]
                if index < len(
                    items
                )
                else ""
            )

            self._draw_wrapped(
                draw,
                body,
                (
                    x1 + 45,
                    675,
                ),
                self._font(
                    31,
                ),
                max_width=450,
                max_lines=5,
                fill=self.TEXT,
            )

    def _outro(
        self,
        draw: ImageDraw.ImageDraw,
        title: str,
    ) -> None:
        self._top_label(
            draw,
            "NEXT",
        )

        draw.rounded_rectangle(
            (
                250,
                260,
                1670,
                850,
            ),
            radius=60,
            fill=self.PANEL,
        )

        self._center_text(
            draw,
            "KEEP WATCHING",
            (
                350,
                360,
                1570,
                520,
            ),
            self._font(
                82,
                bold=True,
            ),
            max_lines=1,
        )

        self._center_text(
            draw,
            self._short(
                title,
                90,
            ),
            (
                410,
                570,
                1510,
                760,
            ),
            self._font(
                42,
            ),
            max_lines=3,
        )

    def _editorial(
        self,
        draw: ImageDraw.ImageDraw,
        title: str,
        description: str,
    ) -> None:
        self._top_label(
            draw,
            "EXPLAINED",
        )
        self._headline_block(
            draw,
            title,
            top=190,
            max_size=88,
        )
        self._summary_bar(
            draw,
            description,
            top=690,
            label="WHY IT MATTERS",
        )

    def _top_label(
        self,
        draw: ImageDraw.ImageDraw,
        label: str,
    ) -> None:
        draw.rounded_rectangle(
            (
                90,
                70,
                500,
                150,
            ),
            radius=28,
            fill=self.PANEL_ALT,
        )
        self._center_text(
            draw,
            label,
            (
                110,
                82,
                480,
                140,
            ),
            self._font(
                27,
                bold=True,
            ),
            max_lines=1,
        )

    def _headline_block(
        self,
        draw: ImageDraw.ImageDraw,
        title: str,
        *,
        top: int,
        max_size: int,
    ) -> None:
        clean = self._short(
            title,
            120,
        )
        font = self._fit_font(
            draw,
            clean,
            max_width=1650,
            max_height=350,
            max_size=max_size,
            min_size=42,
            max_lines=3,
        )

        self._center_text(
            draw,
            clean,
            (
                130,
                top,
                1790,
                top + 360,
            ),
            font,
            max_lines=3,
        )

    def _summary_bar(
        self,
        draw: ImageDraw.ImageDraw,
        description: str,
        *,
        top: int,
        label: str,
    ) -> None:
        draw.rounded_rectangle(
            (
                120,
                top,
                1800,
                min(
                    self.HEIGHT - 70,
                    top + 230,
                ),
            ),
            radius=34,
            fill=self.PANEL,
        )

        draw.text(
            (
                170,
                top + 32,
            ),
            label,
            font=self._font(
                24,
                bold=True,
            ),
            fill=self.MUTED,
        )

        self._draw_wrapped(
            draw,
            self._short(
                description,
                210,
            ),
            (
                170,
                top + 92,
            ),
            self._font(
                34,
            ),
            max_width=1560,
            max_lines=3,
            fill=self.TEXT,
        )

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

    @staticmethod
    def _clauses(
        text: str,
        limit: int,
    ) -> list[str]:
        clean = re.sub(
            r"\s+",
            " ",
            text or "",
        ).strip()

        raw = re.split(
            r"(?<=[.!?])\s+|;\s+|,\s+(?=[A-ZÀ-ÖØ-Ý0-9])",
            clean,
        )

        values = []

        for item in raw:
            item = item.strip(
                " .,:;!-"
            )
            if len(
                item
            ) < 8:
                continue

            values.append(
                ViewerGraphicRenderer._short(
                    item,
                    105,
                )
            )

            if len(
                values
            ) >= limit:
                break

        if not values and clean:
            values.append(
                ViewerGraphicRenderer._short(
                    clean,
                    105,
                )
            )

        return values

    def _fit_font(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        *,
        max_width: int,
        max_height: int,
        max_size: int,
        min_size: int,
        max_lines: int,
    ) -> ImageFont.FreeTypeFont:
        for size in range(
            max_size,
            min_size - 1,
            -3,
        ):
            font = self._font(
                size,
                bold=True,
            )
            lines = self._wrap_lines(
                draw,
                text,
                font,
                max_width,
            )

            if len(
                lines
            ) > max_lines:
                continue

            height = sum(
                (
                    draw.textbbox(
                        (
                            0,
                            0,
                        ),
                        line,
                        font=font,
                    )[3]
                    + 16
                )
                for line in lines
            )

            if height <= max_height:
                return font

        return self._font(
            min_size,
            bold=True,
        )

    def _center_text(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        box: tuple[
            int,
            int,
            int,
            int,
        ],
        font: ImageFont.ImageFont,
        *,
        fill: tuple[
            int,
            int,
            int,
        ] | None = None,
        max_lines: int,
    ) -> None:
        fill = (
            fill
            if fill is not None
            else self.TEXT
        )

        x1, y1, x2, y2 = box
        max_width = (
            x2
            - x1
        )

        lines = self._wrap_lines(
            draw,
            text,
            font,
            max_width,
        )[
            :max_lines
        ]

        if not lines:
            return

        line_boxes = [
            draw.textbbox(
                (
                    0,
                    0,
                ),
                line,
                font=font,
            )
            for line in lines
        ]

        line_heights = [
            box_[3]
            - box_[1]
            for box_ in line_boxes
        ]

        total_height = (
            sum(
                line_heights
            )
            + 16
            * (
                len(
                    lines
                )
                - 1
            )
        )

        y = (
            y1
            + (
                (
                    y2
                    - y1
                )
                - total_height
            )
            / 2
        )

        for line, bbox in zip(
            lines,
            line_boxes,
            strict=True,
        ):
            width = (
                bbox[2]
                - bbox[0]
            )
            height = (
                bbox[3]
                - bbox[1]
            )

            x = (
                x1
                + (
                    max_width
                    - width
                )
                / 2
            )

            draw.text(
                (
                    x,
                    y,
                ),
                line,
                font=font,
                fill=fill,
            )

            y += (
                height
                + 16
            )

    def _draw_wrapped(
        self,
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
        ],
    ) -> None:
        lines = self._wrap_lines(
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
            )
            bbox = draw.textbbox(
                (
                    x,
                    y,
                ),
                line,
                font=font,
            )
            y += (
                bbox[3]
                - bbox[1]
                + 18
            )

    @staticmethod
    def _wrap_lines(
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.ImageFont,
        max_width: int,
    ) -> list[str]:
        words = (
            text
            or ""
        ).split()

        lines: list[str] = []
        current: list[str] = []

        for word in words:
            candidate = " ".join(
                current
                + [
                    word
                ]
            )

            bbox = draw.textbbox(
                (
                    0,
                    0,
                ),
                candidate,
                font=font,
            )

            if (
                bbox[2]
                - bbox[0]
            ) <= max_width:
                current.append(
                    word
                )
                continue

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
    def _panel(
        draw: ImageDraw.ImageDraw,
        box: tuple[
            int,
            int,
            int,
            int,
        ],
    ) -> None:
        draw.rounded_rectangle(
            box,
            radius=42,
            fill=ViewerGraphicRenderer.PANEL,
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
                "/Library/Fonts/Arial.ttf",
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
