from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


class TechnicalVisualRenderer:
    """Deterministic local renderer for technical YouTube visuals."""

    WIDTH = 1280
    HEIGHT = 720

    def render(
        self,
        *,
        title: str,
        description: str,
        visual_type: str,
        output_path: str,
    ) -> None:
        """Render a simple technical slide/diagram locally with Pillow."""

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        image = Image.new(
            "RGB",
            (self.WIDTH, self.HEIGHT),
            (20, 24, 32),
        )

        draw = ImageDraw.Draw(image)

        title_font = self._load_font(42)
        body_font = self._load_font(28)
        small_font = self._load_font(22)

        # Header
        draw.rounded_rectangle(
            (50, 40, self.WIDTH - 50, 130),
            radius=18,
            fill=(35, 42, 56),
        )

        draw.text(
            (80, 68),
            title,
            font=title_font,
            fill=(245, 245, 245),
        )

        visual_type_normalized = (visual_type or "technical").replace("_", " ").upper()

        draw.rounded_rectangle(
            (50, 160, 280, 215),
            radius=14,
            fill=(48, 58, 75),
        )

        draw.text(
            (70, 175),
            visual_type_normalized,
            font=small_font,
            fill=(225, 230, 240),
        )

        # Main technical content area
        draw.rounded_rectangle(
            (50, 245, self.WIDTH - 50, self.HEIGHT - 60),
            radius=22,
            outline=(90, 105, 130),
            width=3,
            fill=(28, 34, 45),
        )

        wrapped_lines = self._wrap_text(
            description,
            max_chars=62,
        )

        y = 290

        for line in wrapped_lines[:10]:
            draw.text(
                (85, y),
                line,
                font=body_font,
                fill=(232, 235, 240),
            )
            y += 42

        # Simple workflow accents
        if any(
            keyword in visual_type_normalized.lower()
            for keyword in (
                "workflow",
                "architecture",
                "api",
                "pipeline",
                "automation",
                "code",
                "dashboard",
            )
        ):
            self._draw_visual_hint(
                draw,
                visual_type_normalized.lower(),
            )

        image.save(path, format="PNG")

    def _draw_visual_hint(
        self,
        draw: ImageDraw.ImageDraw,
        visual_type: str,
    ) -> None:
        """Add a simple deterministic visual cue."""

        y = self.HEIGHT - 125

        if "api" in visual_type:
            labels = ["REQUEST", "API", "RESPONSE"]
        elif "workflow" in visual_type or "pipeline" in visual_type:
            labels = ["INPUT", "PROCESS", "OUTPUT"]
        elif "architecture" in visual_type:
            labels = ["CLIENT", "SERVICE", "DATA"]
        elif "code" in visual_type:
            labels = ["PROMPT", "CODE", "TEST"]
        elif "dashboard" in visual_type:
            labels = ["RUN", "RESULT", "ANALYSIS"]
        else:
            labels = ["SOURCE", "AGENT", "RESULT"]

        x_positions = [140, 500, 860]

        for index, (x, label) in enumerate(
            zip(x_positions, labels, strict=True)
        ):
            draw.rounded_rectangle(
                (x, y - 35, x + 220, y + 35),
                radius=14,
                fill=(43, 52, 67),
                outline=(110, 125, 150),
                width=2,
            )

            font = self._load_font(20)

            draw.text(
                (x + 28, y - 12),
                label,
                font=font,
                fill=(240, 240, 240),
            )

            if index < 2:
                start_x = x + 220
                end_x = x_positions[index + 1]

                draw.line(
                    (start_x + 15, y, end_x - 15, y),
                    fill=(150, 165, 190),
                    width=4,
                )

                draw.polygon(
                    [
                        (end_x - 25, y - 8),
                        (end_x - 10, y),
                        (end_x - 25, y + 8),
                    ],
                    fill=(150, 165, 190),
                )

    @staticmethod
    def _wrap_text(
        text: str,
        *,
        max_chars: int,
    ) -> list[str]:
        words = text.split()

        lines: list[str] = []
        current: list[str] = []

        for word in words:
            candidate = " ".join(current + [word])

            if len(candidate) <= max_chars:
                current.append(word)
            else:
                if current:
                    lines.append(" ".join(current))
                current = [word]

        if current:
            lines.append(" ".join(current))

        return lines

    @staticmethod
    def _load_font(
        size: int,
    ) -> ImageFont.ImageFont:
        """Use a common macOS font when available, otherwise Pillow default."""

        candidates = [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/Library/Fonts/Arial.ttf",
        ]

        for candidate in candidates:
            if Path(candidate).exists():
                try:
                    return ImageFont.truetype(
                        candidate,
                        size=size,
                    )
                except OSError:
                    continue

        return ImageFont.load_default()
