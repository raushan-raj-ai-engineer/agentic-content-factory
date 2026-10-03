from __future__ import annotations

import hashlib
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from content_factory.visual.study_semantics import StudySemanticPlanner


class StudyBackdropRenderer:
    """Fast deterministic cinematic ambience for Study Mode.

    This renderer deliberately draws *no readable text*. Exact titles, labels,
    code, equations, and teaching copy belong to the Manim layer where glyphs
    are deterministic. The backdrop only provides premium depth and scene-
    specific visual energy.
    """

    WIDTH = 1920
    HEIGHT = 1080

    BG_TOP = (5, 9, 20)
    BG_BOTTOM = (8, 18, 34)
    CYAN = (34, 211, 238)
    BLUE = (59, 130, 246)
    PURPLE = (139, 92, 246)
    VIOLET = (192, 132, 252)
    GREEN = (45, 212, 191)
    GRID = (40, 62, 92)

    def render(
        self,
        *,
        title: str,
        description: str,
        visual_type: str,
        output_path: str,
        topic: str | None = None,
        scene_index: int = 0,
    ) -> None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        plan = StudySemanticPlanner.plan_scene(
            scene_id=max(0, scene_index),
            topic=(topic or title),
            title=title,
            description=description,
            key_elements=[],
            visual_type=visual_type,
        )

        seed = self._seed(topic or "", title, description, visual_type, str(scene_index))
        rng = random.Random(seed)

        image = self._gradient_background()
        self._add_radial_glow(image, (470, 560), 520, self.CYAN, 44)
        self._add_radial_glow(image, (1460, 420), 620, self.PURPLE, 38)
        self._add_radial_glow(image, (980, 900), 460, self.BLUE, 20)

        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        self._grid(draw)
        self._stars(draw, rng, 70)

        archetype = plan.archetype
        if archetype in {"architecture_network", "concept_map", "many_to_one"}:
            self._network(draw, rng, dense=archetype != "many_to_one")
        elif archetype in {"message_exchange", "request_response", "retrieval_pipeline"}:
            self._flow(draw, rng)
        elif archetype in {"validation_gate", "security_boundary"}:
            self._boundary(draw)
        elif archetype in {"agent_tool_loop", "capability_orbit"}:
            self._orbit(draw, rng)
        elif archetype in {"code_execution", "browser_action", "browser_test", "query_table"}:
            self._code_geometry(draw, rng)
        elif archetype in {"algorithm_trace", "timeline_build"}:
            self._sequence(draw, rng)
        elif archetype in {"equation_focus", "graph_plot", "number_line", "vector_scene"}:
            self._math_geometry(draw)
        elif archetype in {"atom_model", "molecule_model", "wave_model", "experiment_setup"}:
            self._science_geometry(draw, rng)
        else:
            self._network(draw, rng, dense=False)

        # Dark center veil keeps semantic Manim overlays legible while preserving
        # premium cyan/violet edge energy.
        veil = Image.new("RGBA", image.size, (0, 0, 0, 0))
        vd = ImageDraw.Draw(veil)
        vd.rounded_rectangle((220, 120, 1700, 960), radius=90, fill=(4, 10, 24, 72))
        veil = veil.filter(ImageFilter.GaussianBlur(45))

        image = Image.alpha_composite(image.convert("RGBA"), overlay)
        image = Image.alpha_composite(image, veil)
        image.convert("RGB").save(path, "PNG", compress_level=1)

    def _gradient_background(self) -> Image.Image:
        gradient = Image.linear_gradient("L").resize((self.WIDTH, self.HEIGHT))
        return ImageOps.colorize(gradient, self.BG_TOP, self.BG_BOTTOM)

    @staticmethod
    def _seed(*parts: str) -> int:
        digest = hashlib.sha256("|".join(parts).encode("utf-8", errors="ignore")).digest()
        return int.from_bytes(digest[:8], "big")

    @staticmethod
    def _rgba(color: tuple[int, int, int], alpha: int) -> tuple[int, int, int, int]:
        return color[0], color[1], color[2], alpha

    def _add_radial_glow(
        self,
        image: Image.Image,
        center: tuple[int, int],
        radius: int,
        color: tuple[int, int, int],
        alpha: int,
    ) -> None:
        layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        cx, cy = center
        steps = 14
        for i in range(steps, 0, -1):
            frac = i / steps
            rr = int(radius * frac)
            aa = max(1, int(alpha * (1 - frac + 0.08) ** 1.6))
            draw.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=self._rgba(color, aa))
        layer = layer.filter(ImageFilter.GaussianBlur(45))
        image.paste(layer, (0, 0), layer)

    def _grid(self, draw: ImageDraw.ImageDraw) -> None:
        for x in range(0, self.WIDTH, 120):
            draw.line((x, 0, x, self.HEIGHT), fill=self._rgba(self.GRID, 23), width=1)
        for y in range(0, self.HEIGHT, 120):
            draw.line((0, y, self.WIDTH, y), fill=self._rgba(self.GRID, 20), width=1)

    def _stars(self, draw: ImageDraw.ImageDraw, rng: random.Random, count: int) -> None:
        for _ in range(count):
            x = rng.randrange(50, self.WIDTH - 50)
            y = rng.randrange(40, self.HEIGHT - 40)
            radius = rng.choice((1, 1, 1, 2))
            color = rng.choice((self.CYAN, self.BLUE, self.PURPLE))
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=self._rgba(color, rng.randrange(35, 95)))

    def _network(self, draw: ImageDraw.ImageDraw, rng: random.Random, *, dense: bool) -> None:
        count = 18 if dense else 11
        pts: list[tuple[int, int]] = []
        for _ in range(count):
            x = rng.randrange(260, 1660)
            y = rng.randrange(250, 850)
            pts.append((x, y))
        for i, p in enumerate(pts):
            nearest = sorted(pts[:i] + pts[i + 1 :], key=lambda q: (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2)[:2]
            for q in nearest:
                draw.line((*p, *q), fill=self._rgba(self.BLUE, 45), width=2)
        for i, (x, y) in enumerate(pts):
            c = (self.CYAN, self.PURPLE, self.BLUE)[i % 3]
            r = 5 if i % 4 else 9
            draw.ellipse((x - r, y - r, x + r, y + r), fill=self._rgba(c, 150), outline=self._rgba(c, 220), width=2)

    def _flow(self, draw: ImageDraw.ImageDraw, rng: random.Random) -> None:
        y = 555
        xs = [300, 730, 1160, 1590]
        for i, x in enumerate(xs):
            c = (self.CYAN, self.BLUE, self.PURPLE, self.GREEN)[i]
            draw.rounded_rectangle((x - 105, y - 70, x + 105, y + 70), radius=28, outline=self._rgba(c, 120), width=4, fill=(8, 20, 38, 90))
            if i < len(xs) - 1:
                draw.line((x + 110, y, xs[i + 1] - 120, y), fill=self._rgba(c, 100), width=5)
                for step in range(3):
                    px = x + 160 + step * 80
                    draw.ellipse((px - 5, y - 5, px + 5, y + 5), fill=self._rgba(self.CYAN, 160))
        for _ in range(8):
            x = rng.randrange(320, 1600)
            yy = y + rng.choice((-185, 185))
            draw.line((x - 70, yy, x + 70, yy), fill=self._rgba(self.PURPLE, 45), width=2)

    def _boundary(self, draw: ImageDraw.ImageDraw) -> None:
        draw.rounded_rectangle((760, 250, 1160, 830), radius=80, fill=(7, 18, 36, 95), outline=self._rgba(self.PURPLE, 100), width=5)
        draw.arc((835, 335, 1085, 585), start=200, end=340, fill=self._rgba(self.CYAN, 170), width=8)
        draw.line((960, 470, 960, 675), fill=self._rgba(self.CYAN, 130), width=8)
        draw.ellipse((920, 650, 1000, 730), outline=self._rgba(self.CYAN, 140), width=6)
        for x in (370, 1460):
            draw.line((x, 540, 690 if x < 960 else 1230, 540), fill=self._rgba(self.BLUE, 80), width=4)

    def _orbit(self, draw: ImageDraw.ImageDraw, rng: random.Random) -> None:
        cx, cy = 960, 555
        for r, color, alpha in ((120, self.CYAN, 130), (230, self.PURPLE, 90), (350, self.BLUE, 55)):
            draw.ellipse((cx - r, cy - int(r * 0.55), cx + r, cy + int(r * 0.55)), outline=self._rgba(color, alpha), width=4)
        draw.ellipse((cx - 65, cy - 65, cx + 65, cy + 65), fill=self._rgba(self.CYAN, 50), outline=self._rgba(self.CYAN, 190), width=5)
        for angle in (35, 155, 275):
            rad = math.radians(angle)
            x = cx + int(350 * math.cos(rad))
            y = cy + int(190 * math.sin(rad))
            draw.ellipse((x - 24, y - 24, x + 24, y + 24), fill=self._rgba(self.PURPLE, 80), outline=self._rgba(self.PURPLE, 170), width=3)

    def _code_geometry(self, draw: ImageDraw.ImageDraw, rng: random.Random) -> None:
        boxes = [(250, 250, 820, 840), (1110, 320, 1660, 780)]
        for bi, box in enumerate(boxes):
            x1, y1, x2, y2 = box
            draw.rounded_rectangle(box, radius=34, fill=(7, 15, 31, 120), outline=self._rgba(self.BLUE if bi == 0 else self.PURPLE, 90), width=3)
            for i in range(8):
                y = y1 + 85 + i * 52
                maxw = (x2 - x1) - 120
                w = rng.randrange(int(maxw * 0.38), maxw)
                color = (self.CYAN, self.BLUE, self.PURPLE, self.GREEN)[i % 4]
                draw.rounded_rectangle((x1 + 55, y, x1 + 55 + w, y + 10), radius=5, fill=self._rgba(color, 75))
        draw.line((820, 545, 1110, 545), fill=self._rgba(self.CYAN, 110), width=5)

    def _sequence(self, draw: ImageDraw.ImageDraw, rng: random.Random) -> None:
        y = 585
        draw.line((250, y, 1670, y), fill=self._rgba(self.BLUE, 80), width=5)
        for i, x in enumerate((320, 720, 1120, 1520)):
            c = (self.CYAN, self.BLUE, self.PURPLE, self.GREEN)[i]
            draw.ellipse((x - 28, y - 28, x + 28, y + 28), fill=self._rgba(c, 120), outline=self._rgba(c, 210), width=4)
            draw.line((x, y - 35, x, y - 150 if i % 2 == 0 else y + 150), fill=self._rgba(c, 60), width=3)

    def _math_geometry(self, draw: ImageDraw.ImageDraw) -> None:
        ox, oy = 960, 590
        draw.line((300, oy, 1620, oy), fill=self._rgba(self.CYAN, 85), width=3)
        draw.line((ox, 230, ox, 880), fill=self._rgba(self.CYAN, 85), width=3)
        pts = []
        for x in range(-600, 601, 20):
            xx = ox + x
            yy = oy - int(180 * math.sin(x / 140.0))
            pts.append((xx, yy))
        draw.line(pts, fill=self._rgba(self.PURPLE, 150), width=5)

    def _science_geometry(self, draw: ImageDraw.ImageDraw, rng: random.Random) -> None:
        cx, cy = 960, 555
        draw.ellipse((cx - 55, cy - 55, cx + 55, cy + 55), fill=self._rgba(self.CYAN, 80), outline=self._rgba(self.CYAN, 190), width=4)
        for angle in (0, 60, 120):
            box = (cx - 300, cy - 120, cx + 300, cy + 120)
            draw.arc(box, start=angle, end=angle + 250, fill=self._rgba(self.PURPLE, 100), width=4)
        for x in range(300, 1600, 28):
            y = 835 + int(28 * math.sin(x / 70))
            draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=self._rgba(self.BLUE, 95))
