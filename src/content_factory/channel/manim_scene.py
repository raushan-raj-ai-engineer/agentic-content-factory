"""Trusted 1080p renderer for deterministic educational scene JSON.

Scene JSON is data; generated Python is never executed.
"""

import json
import os
import textwrap
from pathlib import Path

from manim import *


BG = "#08111F"
TEAL = "#5EEAD4"
MUTED = "#64748B"
TEXT = "#DBEAFE"
PURPLE = "#A78BFA"
GOLD = "#FBBF24"


class ChannelScene(Scene):
    def construct(self):
        spec = json.loads(Path(os.environ["CHANNEL_SCENE"]).read_text(encoding="utf-8"))
        total_seconds = max(1.2, float(spec["seconds"]))
        self.camera.background_color = BG
        spent = 0.0

        kicker = Text("CODE  →  UNDERSTAND  →  VERIFY", font_size=20, color=TEAL).to_corner(UL, buff=0.22)
        stage = Text(str(spec.get("stage") or "explain").replace("-", " ").upper(), font_size=17, color="#C4B5FD")
        stage.to_corner(UR, buff=0.25)
        self.add(kicker, stage)

        title = Text(spec["title"], font_size=46, color=WHITE)
        if title.width > 12.2:
            title.scale_to_fit_width(12.2)
        title.to_edge(UP, buff=0.72)
        self.play(FadeIn(title, shift=DOWN * 0.12), run_time=0.28)
        spent += 0.28

        goal_text = str(spec.get("learning_goal") or "").strip()
        if goal_text:
            goal = Text(textwrap.shorten(goal_text, width=120, placeholder="…"), font_size=19, color="#94A3B8")
            if goal.width > 12.0:
                goal.scale_to_fit_width(12.0)
            goal.next_to(title, DOWN, buff=0.17)
            self.play(FadeIn(goal), run_time=0.20)
            spent += 0.20

        if spec.get("code"):
            spent += self._render_code(spec)
        else:
            spent += self._render_trace(spec)

        footer = Text(
            f"{spec['index'] + 1:02d} / {spec['total']:02d}   •   SME study lesson   •   1080p",
            font_size=17,
            color=MUTED,
        ).to_edge(DOWN, buff=0.18)
        self.add(footer)

        remaining = total_seconds - spent
        if remaining > 0.05:
            self.wait(remaining)

    def _render_code(self, spec: dict) -> float:
        spent = 0.0
        lines = str(spec["code"]).splitlines()
        code_group = VGroup()
        size = 27 if len(lines) <= 10 else 23
        for idx, line in enumerate(lines, start=1):
            line_no = Text(f"{idx:>2}", font="Monospace", font_size=size - 4, color=MUTED)
            body = Text(line or " ", font="Monospace", font_size=size, color=TEXT)
            row = VGroup(line_no, body).arrange(RIGHT, buff=0.28, aligned_edge=UP)
            code_group.add(row)
        code_group.arrange(DOWN, aligned_edge=LEFT, buff=0.11)
        if code_group.width > 12.0:
            code_group.scale_to_fit_width(12.0)
        if code_group.height > 5.2:
            code_group.scale_to_fit_height(5.2)
        code_group.move_to(DOWN * 0.15)

        # Progressive line reveal keeps code readable and gives the eye a path.
        self.play(LaggedStart(*[FadeIn(row, shift=RIGHT * 0.08) for row in code_group], lag_ratio=0.06), run_time=1.05)
        spent += 1.05

        callout_text = str(spec.get("callout") or "").strip()
        if callout_text:
            callout = self._pill(callout_text, TEAL, "#12352F", y=-3.05)
            self.play(FadeIn(callout, shift=UP * 0.08), run_time=0.30)
            spent += 0.30
        return spent

    def _render_trace(self, spec: dict) -> float:
        spent = 0.0
        values = list(spec.get("values", []))
        inactive = set(spec.get("inactive", []))
        active = set(spec.get("active", []))
        pointers = dict(spec.get("pointers", {}))

        cells = VGroup()
        cell_map = {}
        for index, value in enumerate(values):
            is_active = index in active
            is_inactive = index in inactive
            box = RoundedRectangle(
                width=1.65,
                height=0.92,
                corner_radius=0.12,
                stroke_color=TEAL if is_active else ("#334155" if is_inactive else "#64748B"),
                fill_color="#0F2D2A" if is_active else ("#111827" if is_inactive else "#17243A"),
                fill_opacity=1,
                stroke_width=3 if is_active else 2,
            )
            label = Text(repr(value) if value == " " else value, font_size=28, color=MUTED if is_inactive else WHITE)
            if label.width > 1.35:
                label.scale_to_fit_width(1.35)
            label.move_to(box)
            idx = Text(str(index), font_size=16, color=MUTED).next_to(box, DOWN, buff=0.10)
            cell = VGroup(box, label, idx)
            if is_inactive:
                slash1 = Line(box.get_corner(UL) + RIGHT * 0.15 + DOWN * 0.10, box.get_corner(DR) + LEFT * 0.15 + UP * 0.10, color="#475569", stroke_width=4)
                slash2 = Line(box.get_corner(UR) + LEFT * 0.15 + DOWN * 0.10, box.get_corner(DL) + RIGHT * 0.15 + UP * 0.10, color="#475569", stroke_width=4)
                cell.add(slash1, slash2)
            cells.add(cell)
            cell_map[index] = cell

        cols = min(7, max(1, len(values)))
        rows = (len(values) + cols - 1) // cols if values else 1
        if values:
            cells.arrange_in_grid(rows=rows, cols=cols, buff=(0.28, 0.54), fill_rows_first=True)
            if cells.width > 12.0:
                cells.scale_to_fit_width(12.0)
            cells.move_to(UP * (0.75 if rows == 1 else 0.9))
            self.play(LaggedStart(*[FadeIn(c, shift=UP * 0.08) for c in cells], lag_ratio=0.04), run_time=0.65)
            spent += 0.65

            # Pointer labels appear after the array is visible so the learner
            # can first establish the state, then inspect its meaning.
            pointer_groups: dict[int, list[str]] = {}
            for name, idx in pointers.items():
                if isinstance(idx, int) and idx in cell_map:
                    pointer_groups.setdefault(idx, []).append(str(name))
            pointer_mobs = []
            for idx, names in pointer_groups.items():
                target = cell_map[idx]
                triangle = Triangle(color=GOLD, fill_opacity=1).scale(0.09).rotate(PI).next_to(target, UP, buff=0.05)
                label = Text("/".join(names), font="Monospace", font_size=15, color="#FDE68A").next_to(triangle, UP, buff=0.05)
                pointer_mobs.append(VGroup(triangle, label))
            if pointer_mobs:
                self.play(LaggedStart(*[FadeIn(mob, shift=DOWN * 0.05) for mob in pointer_mobs], lag_ratio=0.08), run_time=0.35)
                spent += 0.35
        else:
            self.wait(0.25)
            spent += 0.25

        comparison_text = str(spec.get("comparison") or "").strip()
        detail_text = str(spec.get("detail") or "").strip()
        callout_text = str(spec.get("callout") or "").strip()

        current_y = -1.70 if rows == 1 else -2.25
        if comparison_text:
            comparison = self._pill(comparison_text, "#EDE9FE", "#271B36", y=current_y, border=PURPLE, mono=True)
            self.play(FadeIn(comparison, shift=UP * 0.08), run_time=0.30)
            spent += 0.30
            current_y -= 0.75

        if detail_text:
            wrapped = "\n".join(textwrap.fill(line, width=76) for line in detail_text.splitlines())
            detail = Text(wrapped, font="Monospace", font_size=20, line_spacing=0.9, color=TEXT)
            if detail.width > 11.8:
                detail.scale_to_fit_width(11.8)
            if detail.height > 1.0:
                detail.scale_to_fit_height(1.0)
            detail.move_to([0, current_y, 0])
            self.play(FadeIn(detail), run_time=0.26)
            spent += 0.26
            current_y -= 0.72

        if callout_text:
            callout = self._pill(callout_text, "#CCFBF1", "#12352F", y=max(-3.05, current_y), border=TEAL)
            self.play(FadeIn(callout, shift=UP * 0.06), run_time=0.28)
            spent += 0.28

        return spent

    @staticmethod
    def _pill(text: str, color: str, fill: str, *, y: float, border: str | None = None, mono: bool = False) -> VGroup:
        label = Text(text, font="Monospace" if mono else "Arial", font_size=22, color=color)
        if label.width > 10.8:
            label.scale_to_fit_width(10.8)
        box = RoundedRectangle(
            width=min(11.7, max(3.2, label.width + 0.65)),
            height=max(0.52, label.height + 0.28),
            corner_radius=0.12,
            fill_color=fill,
            fill_opacity=1,
            stroke_color=border or fill,
            stroke_width=2,
        )
        label.move_to(box)
        group = VGroup(box, label)
        group.move_to([0, y, 0])
        return group
