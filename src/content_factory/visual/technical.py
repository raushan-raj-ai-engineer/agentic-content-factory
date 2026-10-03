from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from content_factory.visual.study_semantics import StudySemanticPlanner


class TechnicalVisualRenderer:
    """Scene-specific 1080p reference art for technical study scenes.

    These PNGs are contextual assets for the semantic Manim renderer. They are
    intentionally *not* a reusable flow-chart template and are not the primary
    animation surface.
    """

    WIDTH = 1920
    HEIGHT = 1080
    BG = (8, 17, 31)
    PANEL = (16, 29, 48)
    PANEL2 = (23, 36, 58)
    TEXT = (241, 245, 249)
    MUTED = (148, 163, 184)
    TEAL = (94, 234, 212)
    PURPLE = (196, 181, 253)
    GOLD = (251, 191, 36)
    GREEN = (110, 231, 183)
    RED = (251, 113, 133)
    BLUE = (125, 211, 252)

    def render(
        self,
        *,
        title: str,
        description: str,
        visual_type: str,
        output_path: str,
        topic: str | None = None,
    ) -> None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        plan = StudySemanticPlanner.plan_scene(
            scene_id=0,
            topic=(topic or title),
            title=title,
            description=description,
            key_elements=[],
            visual_type=visual_type,
        )

        image = Image.new("RGB", (self.WIDTH, self.HEIGHT), self.BG)
        draw = ImageDraw.Draw(image)
        self._header(draw, title, plan.archetype)

        renderer = getattr(self, f"_draw_{plan.archetype}", self._draw_concept_reveal)
        renderer(draw, plan.labels, description)

        draw.text(
            (82, 1020),
            "Scene-specific reference art • live teaching animation rendered separately",
            font=self._font(22),
            fill=self.MUTED,
        )
        image.save(path, format="PNG")

    def _header(self, d: ImageDraw.ImageDraw, title: str, archetype: str) -> None:
        d.text((80, 48), "STUDY VISUAL REFERENCE", font=self._font(26), fill=self.TEAL)
        fitted, font = self._fit(d, title, 1600, 58, 34)
        d.text((80, 105), fitted, font=font, fill=self.TEXT)
        badge = archetype.replace("_", " ").upper()
        bw = min(620, 80 + int(d.textlength(badge, font=self._font(22))))
        d.rounded_rectangle((80, 205, 80 + bw, 260), radius=16, fill=(19, 34, 56))
        d.text((106, 220), badge, font=self._font(22), fill=self.PURPLE)

    def _labels(self, labels: list[str], fallback: list[str]) -> list[str]:
        values = [self._short(v) for v in labels if v.strip()]
        for item in fallback:
            if len(values) >= 5:
                break
            if item.lower() not in {v.lower() for v in values}:
                values.append(item)
        return values[:5]

    def _node(self, d: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str, color: tuple[int, int, int]) -> None:
        d.rounded_rectangle(box, radius=24, fill=self.PANEL, outline=color, width=3)
        x1, y1, x2, y2 = box
        label, font = self._fit(d, text, x2 - x1 - 50, 30, 22)
        tw = d.textlength(label, font=font)
        d.text((x1 + (x2 - x1 - tw) / 2, y1 + (y2 - y1 - font.size) / 2 - 3), label, font=font, fill=self.TEXT)

    def _arrow(self, d: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], color: tuple[int, int, int]) -> None:
        d.line((*start, *end), fill=color, width=6)
        ex, ey = end
        if abs(end[0] - start[0]) >= abs(end[1] - start[1]):
            direction = 1 if end[0] > start[0] else -1
            d.polygon([(ex, ey), (ex - 22 * direction, ey - 12), (ex - 22 * direction, ey + 12)], fill=color)
        else:
            direction = 1 if end[1] > start[1] else -1
            d.polygon([(ex, ey), (ex - 12, ey - 22 * direction), (ex + 12, ey - 22 * direction)], fill=color)

    def _draw_architecture_network(self, d, labels, _description):
        n = self._labels(labels, ["Host", "Client", "Server", "Tool"])
        boxes = [(120, 390, 500, 520), (650, 390, 1030, 520), (1180, 390, 1560, 520), (650, 720, 1030, 850)]
        colors = [self.BLUE, self.TEAL, self.PURPLE, self.GREEN]
        for box, label, color in zip(boxes, n[:4], colors, strict=False):
            self._node(d, box, label, color)
        self._arrow(d, (500, 455), (650, 455), self.BLUE)
        self._arrow(d, (1030, 455), (1180, 455), self.TEAL)
        self._arrow(d, (840, 520), (840, 720), self.PURPLE)

    def _draw_many_to_one(self, d, labels, _description):
        n = self._labels(labels, ["Custom A", "Custom B", "Custom C", "Standard", "Reusable"])
        ys = [360, 520, 680]
        for y, label in zip(ys, n[:3], strict=False):
            self._node(d, (120, y, 470, y + 105), label, self.PURPLE)
            self._arrow(d, (470, y + 52), (780, 555), self.PURPLE)
        self._node(d, (780, 485, 1120, 625), n[3] if len(n) > 3 else "Standard", self.TEAL)
        self._arrow(d, (1120, 555), (1370, 555), self.TEAL)
        self._node(d, (1370, 485, 1760, 625), n[4] if len(n) > 4 else "Reusable", self.GREEN)

    def _draw_capability_orbit(self, d, labels, _description):
        n = self._labels(labels, ["Core", "Tools", "Resources", "Prompts"])
        cx, cy = 950, 585
        d.ellipse((800, 435, 1100, 735), fill=self.PANEL, outline=self.TEAL, width=5)
        label, font = self._fit(d, n[0], 230, 30, 21)
        d.text((cx - d.textlength(label, font=font)/2, cy - 18), label, font=font, fill=self.TEXT)
        positions = [(280, 420), (1430, 420), (850, 820)]
        colors = [self.PURPLE, self.BLUE, self.GREEN]
        for (x, y), label, color in zip(positions, n[1:4], colors, strict=False):
            self._node(d, (x, y, x + 330, y + 110), label, color)
            self._arrow(d, (cx, cy), (x + 165, y + 55), color)

    def _draw_message_exchange(self, d, labels, _description):
        n = self._labels(labels, ["Client", "Server", "Request", "Response"])
        self._node(d, (120, 430, 520, 590), n[0], self.BLUE)
        self._node(d, (1400, 430, 1800, 590), n[1] if len(n) > 1 else "Server", self.TEAL)
        self._arrow(d, (520, 470), (1400, 470), self.GOLD)
        self._arrow(d, (1400, 555), (520, 555), self.GREEN)
        d.text((790, 405), n[2] if len(n) > 2 else "request", font=self._font(28), fill=self.GOLD)
        d.text((790, 585), n[3] if len(n) > 3 else "response", font=self._font(28), fill=self.GREEN)

    def _draw_request_response(self, d, labels, description):
        self._draw_message_exchange(d, labels, description)

    def _draw_validation_gate(self, d, labels, _description):
        n = self._labels(labels, ["Input", "Validation", "Valid", "Rejected"])
        self._node(d, (120, 470, 500, 600), n[0], self.BLUE)
        self._node(d, (760, 380, 1160, 690), n[1] if len(n) > 1 else "Validation", self.GOLD)
        self._node(d, (1390, 360, 1770, 490), n[2] if len(n) > 2 else "Valid", self.GREEN)
        self._node(d, (1390, 650, 1770, 780), n[3] if len(n) > 3 else "Rejected", self.RED)
        self._arrow(d, (500, 535), (760, 535), self.BLUE)
        self._arrow(d, (1160, 480), (1390, 425), self.GREEN)
        self._arrow(d, (1160, 595), (1390, 715), self.RED)

    def _draw_security_boundary(self, d, labels, _description):
        n = self._labels(labels, ["Caller", "Protected resource", "Permission check"])
        d.rounded_rectangle((760, 330, 1770, 860), radius=36, fill=(25, 22, 35), outline=self.RED, width=5)
        self._node(d, (120, 475, 500, 605), n[0], self.BLUE)
        self._node(d, (1090, 500, 1490, 630), n[1] if len(n) > 1 else "Protected", self.GREEN)
        self._node(d, (760, 690, 1130, 810), n[2] if len(n) > 2 else "Permission", self.GOLD)
        self._arrow(d, (500, 540), (760, 540), self.RED)
        d.text((800, 355), "TRUST BOUNDARY", font=self._font(27), fill=self.RED)

    def _draw_tradeoff_balance(self, d, labels, _description):
        n = self._labels(labels, ["Benefit", "Responsibility", "Design takeaway"])
        self._node(d, (180, 420, 730, 580), n[0], self.GREEN)
        self._node(d, (1190, 420, 1740, 580), n[1] if len(n) > 1 else "Responsibility", self.RED)
        d.line((500, 720, 1420, 720), fill=self.GOLD, width=7)
        d.polygon([(960, 720), (900, 830), (1020, 830)], fill=self.GOLD)
        self._node(d, (690, 850, 1230, 960), n[2] if len(n) > 2 else "Design deliberately", self.TEAL)

    def _draw_retrieval_pipeline(self, d, labels, _description):
        n = self._labels(labels, ["Documents", "Vector index", "Context", "Answer"])
        for i in range(3):
            x = 120 + i * 105
            d.rectangle((x, 430 + i * 18, x + 180, 650 + i * 18), fill=self.PANEL2, outline=self.BLUE, width=3)
        self._node(d, (620, 470, 980, 610), n[1] if len(n) > 1 else "Index", self.PURPLE)
        self._node(d, (1110, 470, 1470, 610), n[2] if len(n) > 2 else "Context", self.TEAL)
        self._node(d, (1380, 760, 1760, 900), n[3] if len(n) > 3 else "Answer", self.GREEN)
        self._arrow(d, (440, 540), (620, 540), self.BLUE)
        self._arrow(d, (980, 540), (1110, 540), self.PURPLE)
        self._arrow(d, (1290, 610), (1510, 760), self.TEAL)
        d.text((125, 700), n[0], font=self._font(27), fill=self.BLUE)

    def _draw_browser_action(self, d, labels, _description):
        n = self._labels(labels, ["Browser", "Target element", "Action"])
        d.rounded_rectangle((180, 340, 1490, 900), radius=30, fill=self.PANEL, outline=self.BLUE, width=4)
        d.rectangle((180, 340, 1490, 410), fill=(30, 41, 59))
        self._node(d, (780, 560, 1180, 680), n[1] if len(n) > 1 else "Target", self.TEAL)
        d.polygon([(450, 760), (490, 850), (520, 805), (570, 855), (600, 825), (550, 775)], fill=self.GOLD)
        self._node(d, (1530, 540, 1810, 660), n[2] if len(n) > 2 else "Action", self.GREEN)

    def _draw_browser_test(self, d, labels, description):
        self._draw_browser_action(d, labels, description)
        d.ellipse((1600, 740, 1720, 860), fill=self.GREEN)
        d.text((1634, 754), "✓", font=self._font(68), fill=(5, 40, 30))

    def _draw_query_table(self, d, labels, _description):
        n = self._labels(labels, ["Query", "Rows", "Result"])
        x0, y0 = 720, 360
        for r in range(5):
            for c in range(4):
                fill = (22, 52, 62) if r == 3 else self.PANEL
                d.rectangle((x0 + c*210, y0 + r*95, x0 + (c+1)*210, y0 + (r+1)*95), fill=fill, outline=(71, 85, 105), width=2)
        self._node(d, (120, 500, 520, 640), n[0], self.GOLD)
        self._arrow(d, (520, 570), (720, 570), self.GOLD)
        self._node(d, (1230, 880, 1740, 990), n[2] if len(n) > 2 else "Result", self.GREEN)

    def _draw_algorithm_trace(self, d, labels, _description):
        n = self._labels(labels, ["0", "1", "2", "3", "4"])
        x = 180
        for i, label in enumerate(n[:5]):
            box = (x + i*310, 500, x + i*310 + 250, 650)
            self._node(d, box, label, self.BLUE if i != 2 else self.GOLD)
            d.text((box[0]+105, 675), str(i), font=self._font(22), fill=self.MUTED)
        d.polygon([(930, 420), (970, 475), (890, 475)], fill=self.GOLD)

    def _draw_agent_tool_loop(self, d, labels, _description):
        n = self._labels(labels, ["Agent", "Tool", "Observation"])
        d.ellipse((260, 430, 560, 730), fill=(18, 53, 47), outline=self.TEAL, width=4)
        d.text((330, 545), n[0], font=self._font(30), fill=self.TEXT)
        self._node(d, (1200, 360, 1600, 500), n[1] if len(n) > 1 else "Tool", self.PURPLE)
        self._node(d, (1200, 700, 1600, 840), n[2] if len(n) > 2 else "Observation", self.BLUE)
        self._arrow(d, (560, 500), (1200, 430), self.PURPLE)
        self._arrow(d, (1400, 500), (1400, 700), self.BLUE)
        self._arrow(d, (1200, 770), (560, 660), self.TEAL)

    def _draw_analogy_transform(self, d, labels, _description):
        n = self._labels(labels, ["Real-world analogy", "Technical model", "Mapped idea"])
        self._node(d, (180, 470, 700, 650), n[0], self.GOLD)
        d.text((900, 500), "≈", font=self._font(100), fill=self.PURPLE)
        self._node(d, (1190, 470, 1710, 650), n[1] if len(n) > 1 else "Technical model", self.TEAL)
        self._node(d, (660, 800, 1260, 930), n[2] if len(n) > 2 else "Mapped idea", self.BLUE)

    def _draw_timeline_build(self, d, labels, _description):
        n = self._labels(labels, ["Start", "Stage 2", "Stage 3", "End"])
        d.line((180, 600, 1740, 600), fill=(71, 85, 105), width=8)
        xs = [220, 720, 1220, 1700]
        colors = [self.BLUE, self.PURPLE, self.TEAL, self.GREEN]
        for x, label, color in zip(xs, n[:4], colors, strict=False):
            d.ellipse((x-24, 576, x+24, 624), fill=color)
            text, font = self._fit(d, label, 330, 26, 20)
            d.text((x - d.textlength(text, font=font)/2, 480 if x in (220, 1220) else 665), text, font=font, fill=self.TEXT)

    def _draw_code_execution(self, d, labels, _description):
        n = self._labels(labels, ["define", "validate", "execute", "return"])
        d.rounded_rectangle((180, 330, 1450, 900), radius=30, fill=(10, 18, 32), outline=(51, 65, 85), width=3)
        for i, line in enumerate(n[:5], start=1):
            color = self.GOLD if i == 3 else self.TEXT
            d.text((250, 390 + i*82), f"{i:>2}   {line}", font=self._font(28, mono=True), fill=color)
        self._node(d, (1510, 530, 1810, 670), "OUTPUT", self.GREEN)

    def _draw_concept_map(self, d, labels, _description):
        n = self._labels(labels, ["Core", "Concept A", "Concept B", "Concept C"])
        self._node(d, (760, 500, 1160, 650), n[0], self.TEAL)
        positions = [(130, 350), (1390, 350), (160, 780), (1360, 780)]
        colors = [self.PURPLE, self.BLUE, self.GOLD, self.GREEN]
        for (x, y), label, color in zip(positions, n[1:5], colors, strict=False):
            self._node(d, (x, y, x+370, y+120), label, color)
            self._arrow(d, (x+185, y+60), (960, 575), color)

    def _draw_build_challenge(self, d, labels, _description):
        n = self._labels(labels, ["Goal", "Part A", "Part B", "Verify"])
        self._node(d, (680, 360, 1240, 500), n[0], self.TEAL)
        self._node(d, (220, 700, 620, 820), n[1] if len(n)>1 else "Part A", self.BLUE)
        self._node(d, (760, 700, 1160, 820), n[2] if len(n)>2 else "Part B", self.PURPLE)
        self._node(d, (1300, 700, 1700, 820), n[3] if len(n)>3 else "Verify", self.GREEN)
        self._arrow(d, (420, 700), (800, 500), self.BLUE)
        self._arrow(d, (960, 700), (960, 500), self.PURPLE)
        self._arrow(d, (1500, 700), (1120, 500), self.GREEN)

    def _draw_concept_reveal(self, d, labels, description):
        n = self._labels(labels, ["Core idea", "Mechanism", "Example", "Takeaway"])
        body = self._wrap(d, description, self._font(30), 780)[:6]
        d.rounded_rectangle((110, 360, 970, 900), radius=30, fill=self.PANEL, outline=(51, 65, 85), width=3)
        for i, line in enumerate(body):
            d.text((160, 420 + i*65), line, font=self._font(30), fill=self.TEXT)
        positions = [(1110, 350), (1450, 350), (1110, 690), (1450, 690)]
        colors = [self.BLUE, self.PURPLE, self.TEAL, self.GREEN]
        for (x, y), label, color in zip(positions, n[:4], colors, strict=False):
            self._node(d, (x, y, x+300, y+150), label, color)

    @staticmethod
    def _short(text: str) -> str:
        value = re.sub(r"\s+", " ", text).strip()
        return value if len(value) <= 34 else value[:31].rstrip() + "…"

    @classmethod
    def _fit(cls, d: ImageDraw.ImageDraw, text: str, width: int, start: int, minimum: int):
        value = re.sub(r"\s+", " ", text).strip()
        size = start
        font = cls._font(size)
        while d.textlength(value, font=font) > width and size > minimum:
            size -= 2
            font = cls._font(size)
        while d.textlength(value, font=font) > width and len(value) > 10:
            value = value[:-4] + "…"
        return value, font

    @classmethod
    def _wrap(cls, d: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
        words = re.sub(r"\s+", " ", text).strip().split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if current and d.textlength(candidate, font=font) > max_width:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        return lines

    @staticmethod
    def _font(size: int, mono: bool = False) -> ImageFont.ImageFont:
        candidates = [
            "/System/Library/Fonts/SFNSMono.ttf" if mono else "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf" if mono else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:/Windows/Fonts/consola.ttf" if mono else "C:/Windows/Fonts/arial.ttf",
        ]
        for candidate in candidates:
            if Path(candidate).exists():
                try:
                    return ImageFont.truetype(candidate, size=size)
                except OSError:
                    pass
        return ImageFont.load_default(size=size)
