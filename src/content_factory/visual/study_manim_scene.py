"""Semantic Manim renderer for Study Mode.

The JSON plan is trusted data produced by the application. This module does not
execute generated Python; it maps a finite archetype vocabulary to Manim
objects and animations.
"""

from __future__ import annotations

import json
import math
import os
import re
import textwrap
from pathlib import Path

from manim import (
    BLACK,
    DOWN,
    LEFT,
    ORIGIN,
    RIGHT,
    UP,
    WHITE,
    AnimationGroup,
    Arrow,
    Circle,
    Circumscribe,
    Create,
    CurvedArrow,
    Dot,
    FadeIn,
    FadeOut,
    GrowArrow,
    ImageMobject,
    Indicate,
    LaggedStart,
    Line,
    MoveAlongPath,
    Paragraph,
    Rectangle,
    ReplacementTransform,
    TransformFromCopy,
    RoundedRectangle,
    MovingCameraScene,
    Square,
    SurroundingRectangle,
    Text,
    Triangle,
    VGroup,
    Write,
)

BG = "#07111F"
PANEL = "#18304D"
PANEL_2 = "#23405F"
TEAL = "#5EEAD4"
PURPLE = "#C4B5FD"
GOLD = "#FBBF24"
GREEN = "#6EE7B7"
RED = "#FB7185"
BLUE = "#7DD3FC"
MUTED = "#E2E8F0"
TEXT = "#F8FAFC"


class SemanticStudyScene(MovingCameraScene):
    def construct(self) -> None:
        spec = json.loads(Path(os.environ["STUDY_SCENE_SPEC"]).read_text(encoding="utf-8"))
        self.camera.background_color = BG
        self.total = max(2.0, float(spec.get("seconds") or 2.0))
        self.spent = 0.0
        self._scene_environment = str(spec.get("environment") or "auto")
        self._camera_style = str(spec.get("camera_style") or "auto")
        self._motion_density = str(spec.get("motion_density") or "medium")
        self._environment_backdrop(spec)
        self._camera_home_center = self.camera.frame.get_center().copy()
        self._camera_home_width = float(self.camera.frame.width)
        self.labels = [str(v) for v in spec.get("labels", []) if str(v).strip()][:6]
        if not self.labels:
            self.labels = ["Core idea", "Mechanism", "Verification"]

        if isinstance(spec.get("objects"), list) and isinstance(spec.get("beats"), list):
            self._reference_art(
                str(spec.get("reference_png") or ""),
                ambient=True,
                style=str(spec.get("reference_style") or "semantic_ambient"),
            )
            self._context_title(str(spec.get("title") or ""))
            self._phase_kicker(spec)
            self._render_storyboard(spec)
            return

        self._header(str(spec.get("title") or "Study scene"), str(spec.get("archetype") or "concept"))
        self._reference_art(
            str(spec.get("reference_png") or ""),
            style=str(spec.get("reference_style") or "semantic_ambient"),
        )

        archetype = str(spec.get("archetype") or "concept_reveal")
        renderer = getattr(self, f"_render_{archetype}", self._render_concept_reveal)
        focusables = renderer()
        self._fill_remaining(focusables)

    # ------------------------------------------------------------------
    # Shared composition helpers
    # ------------------------------------------------------------------
    def _header(self, title_text: str, archetype: str) -> None:
        # Legacy semantic plans use the same minimal title treatment as the
        # storyboard renderer. No permanent mode/kicker chrome.
        self._context_title(title_text)
        if getattr(self, "_scene_heading", None) is not None:
            self.wait(min(0.28, max(0.0, self.total - self.spent - 0.4)))
            self.spent += min(0.28, max(0.0, self.total - self.spent - 0.4))
            self._retire_context_title()

    def _reference_art(self, path: str, ambient: bool = False, style: str = "semantic_ambient") -> None:
        if not path or not Path(path).is_file():
            self.reference = None
            return
        image = ImageMobject(path)
        if ambient:
            image.scale_to_fit_width(14.25)
            if image.height < 8.0:
                image.scale_to_fit_height(8.0)
            if style == "hero_ambient":
                image.set_opacity(0.16)
            elif style == "vector_ambient":
                image.set_opacity(0.115)
            elif style == "cinematic_ambient":
                image.set_opacity(0.075)
            else:
                image.set_opacity(0.025)
            self.reference = image
            self.add(image)
            return
        image.scale_to_fit_width(2.8)
        if image.height > 1.65:
            image.scale_to_fit_height(1.65)
        image.to_corner(DOWN + RIGHT, buff=0.26)
        image.set_opacity(0.82 if style == "cinematic_ambient" else 0.72)
        border = SurroundingRectangle(image, color="#52677F", buff=0.04, stroke_width=1.5)
        tag = Text("scene reference", font_size=12, color=MUTED).next_to(border, UP, buff=0.05)
        self.reference = VGroup(border, tag)
        self.add(image, border, tag)

    @staticmethod
    def _clean_display_text(value: object) -> str:
        """Make model/user text safe for Pango without changing its meaning."""
        text = str(value or "").replace("\t", "    ")
        text = "".join(ch if ch in "\n\r" or ord(ch) >= 32 else " " for ch in text)
        return text.strip()

    @classmethod
    def _label(cls, text: str, size: int = 24, color: str = TEXT):
        """Readable label that wraps instead of displaying a broken ellipsis."""
        value = cls._clean_display_text(text) or "•"
        words = value.split()
        if len(words) > 6:
            value = " ".join(words[:6])
        lines = textwrap.wrap(value, width=18, break_long_words=False, break_on_hyphens=False)
        if len(lines) <= 1:
            return Text(value, font_size=size, color=color)
        if len(lines) > 2:
            lines = [lines[0], " ".join(lines[1:])]
        return Paragraph(*lines, font_size=size, color=color, alignment="center", line_spacing=0.82)

    @classmethod
    def _code_text(cls, text: object, size: int = 16, color: str = TEXT) -> Text:
        """Portable non-LaTeX code text.

        Do not name a platform font here: Manim/Pango font-family names differ
        across macOS/Linux/Windows. The default Pango font is guaranteed by the
        working Text renderer, and disable_ligatures keeps code glyph spacing
        predictable enough for educational highlighting.
        """
        value = cls._clean_display_text(text).replace("\n", " ").replace("\r", " ")
        return Text(value or " ", font_size=size, color=color, disable_ligatures=True)

    def _node(self, text: str, color: str = TEAL, width: float = 2.35, height: float = 0.85) -> VGroup:
        box = RoundedRectangle(
            width=width,
            height=height,
            corner_radius=0.14,
            fill_color=PANEL,
            fill_opacity=1,
            stroke_color=color,
            stroke_width=2.4,
        )
        label = self._label(text, 23)
        if label.width > width - 0.32:
            label.scale_to_fit_width(width - 0.32)
        label.move_to(box)
        return VGroup(box, label)

    def _pill(self, text: str, color: str = TEAL) -> VGroup:
        label = self._label(text, 18, color)
        box = RoundedRectangle(
            width=max(1.6, min(4.2, label.width + 0.55)),
            height=0.55,
            corner_radius=0.18,
            fill_color=PANEL_2,
            fill_opacity=1,
            stroke_color=color,
            stroke_width=1.7,
        )
        label.move_to(box)
        return VGroup(box, label)

    def _play(self, animation, run_time: float = 0.7) -> None:
        rt = min(run_time, max(0.0, self.total - self.spent - 0.08))
        if rt <= 0.08:
            return
        self.play(animation, run_time=rt)
        self.spent += rt

    def _fill_remaining(self, focusables: list[object]) -> None:
        remaining = self.total - self.spent
        if remaining <= 0.05:
            return
        mobs = [m for m in focusables if m is not None]
        if not mobs:
            self.wait(remaining)
            return
        idx = 0
        # Keep long narration visually alive with semantic emphasis, never with
        # whole-frame zoom. Each pulse revisits an actual teaching object.
        while self.total - self.spent > 1.05:
            mob = mobs[idx % len(mobs)]
            rt = min(0.75, self.total - self.spent - 0.25)
            if rt <= 0.1:
                break
            self.play(Indicate(mob, color=TEAL, scale_factor=1.025), run_time=rt)
            self.spent += rt
            gap = min(0.45, max(0.0, self.total - self.spent - 0.9))
            if gap > 0.05:
                self.wait(gap)
                self.spent += gap
            idx += 1
        if self.total - self.spent > 0.02:
            self.wait(self.total - self.spent)

    @staticmethod
    def _compact_scene_title(value: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
        if not cleaned:
            return ""
        # Topic prompts often contain a full production brief. On-screen scene
        # headings should read like editorial titles, never command fragments.
        cleaned = re.sub(r"(?i)\s+explained\s+for\s+beginners\s+with\b.*$", " for Beginners", cleaned)
        cleaned = re.sub(r"(?i)\s+with\s+(architecture|retrieval|python|testing|limitations|practice)\b.*$", "", cleaned)
        words = cleaned.split()
        if len(words) > 10:
            cleaned = " ".join(words[:10])
        return cleaned.strip(" .,:;—-")

    def _context_title(self, title_text: str) -> None:
        """Show a brief contextual title without visible truncation."""
        value = self._compact_scene_title(self._clean_display_text(title_text))
        if not value:
            self._scene_heading = None
            return
        lines = textwrap.wrap(value, width=34, break_long_words=False, break_on_hyphens=False)
        if len(lines) > 2:
            lines = [lines[0], " ".join(lines[1:])]
        title = Paragraph(*lines, font_size=30, color=WHITE, alignment="left", line_spacing=0.82)
        if title.width > 10.4:
            title.scale_to_fit_width(10.4)
        title.to_corner(UP + LEFT, buff=0.28)
        underline = Line(title.get_left(), title.get_right(), color=TEAL, stroke_width=2).next_to(title, DOWN, buff=0.08)
        self._scene_heading = VGroup(title, underline)
        self.add(self._scene_heading)

    def _phase_kicker(self, spec: dict[str, object]) -> None:
        """Show the learner where they are in the mini-lesson.

        This is intentionally tiny and temporary: WHAT IT MEANS first, then
        HOW IT FLOWS. It makes chapter progression obvious without becoming a
        quiz card or covering the teaching visual.
        """
        phase = str(spec.get("learning_phase") or "").strip().lower()
        labels = {
            "explain": "1 · THEORY FIRST",
            "flow": "2 · HOW IT FLOWS",
            "example": "3 · EXAMPLE",
            "implementation": "4 · IMPLEMENT",
            "verify": "5 · VERIFY",
            "recap": "RECAP",
        }
        value = labels.get(phase)
        if not value:
            self._phase_heading = None
            return
        accent = GOLD if phase == "explain" else (TEAL if phase == "flow" else BLUE)
        tag = Text(value, font_size=15, color=accent)
        tag.to_corner(UP + RIGHT, buff=0.34)
        self._phase_heading = tag
        self.add(tag)

    def _retire_context_title(self) -> None:
        animations = []
        heading = getattr(self, "_scene_heading", None)
        phase = getattr(self, "_phase_heading", None)
        if heading is not None:
            animations.append(FadeOut(heading, shift=UP * 0.05))
        if phase is not None:
            animations.append(FadeOut(phase, shift=UP * 0.03))
        if animations:
            self._play(AnimationGroup(*animations, lag_ratio=0.0), 0.22)
        self._scene_heading = None
        self._phase_heading = None

    @staticmethod
    def _resolved_environment(spec: dict[str, object]) -> str:
        requested = str(spec.get("environment") or "auto")
        if requested != "auto":
            return requested
        layout = str(spec.get("layout") or "freeform")
        kinds = {
            str(item.get("kind") or "")
            for item in spec.get("objects", [])
            if isinstance(item, dict)
        }
        narration = str(spec.get("description") or "").lower()
        if layout == "code_plus_state" or kinds & {"code", "terminal", "function"}:
            return "code_lab"
        if layout == "browser_demo" or kinds & {"browser", "search_ui"}:
            return "browser_space"
        if layout == "analogy_map":
            return "analogy_warm"
        if layout == "boundary" or kinds & {"gate", "shield", "lock"}:
            return "security_boundary"
        if kinds & {"atom", "molecule", "wave", "experiment"}:
            return "science_lab"
        if kinds & {"vector", "vector_store", "graph", "chart", "point_cloud"}:
            return "data_space"
        if kinds & {"document", "file", "folder", "book", "context_window", "answer_panel"} and any(
            term in narration for term in ("chunk", "document", "context", "source")
        ):
            return "document_space"
        return "technical"

    def _environment_backdrop(self, spec: dict[str, object]) -> None:
        """Build a restrained scene-specific environment behind semantic objects.

        The background is deliberately procedural and lightweight.  It creates
        different visual spaces without relying on a static PNG or random stock
        media, and it is oversized so mild camera reframing never exposes edges.
        """
        environment = self._resolved_environment(spec)
        self._scene_environment = environment
        palette = {
            "technical": ("#07111F", "#12304A", TEAL),
            "data_space": ("#061321", "#102A46", BLUE),
            "code_lab": ("#040A12", "#0B2230", GREEN),
            "browser_space": ("#071421", "#0E2A45", BLUE),
            "document_space": ("#0A111B", "#1B2431", GOLD),
            "analogy_warm": ("#171008", "#2C1B0B", GOLD),
            "security_boundary": ("#07130F", "#102A22", GREEN),
            "science_lab": ("#061316", "#103137", TEAL),
            "clean_light": ("#142333", "#1D3448", BLUE),
        }
        base_color, panel_color, accent = palette.get(environment, palette["technical"])
        self.camera.background_color = base_color
        base = Rectangle(
            width=19.5, height=11.4, fill_color=base_color, fill_opacity=1, stroke_width=0
        )
        halo_left = Circle(
            radius=4.6, fill_color=panel_color, fill_opacity=0.22, stroke_width=0
        ).shift(LEFT * 5.8 + UP * 2.7)
        halo_right = Circle(
            radius=5.2, fill_color=panel_color, fill_opacity=0.15, stroke_width=0
        ).shift(RIGHT * 6.1 + DOWN * 2.5)
        grid = VGroup()
        if environment in {"technical", "data_space", "code_lab", "browser_space", "science_lab"}:
            for x in (-6.0, -4.0, -2.0, 0.0, 2.0, 4.0, 6.0):
                line = Line([x, -5.2, 0], [x, 5.2, 0], color=accent, stroke_width=0.7)
                line.set_opacity(0.075)
                grid.add(line)
            for y in (-3.5, -2.0, -0.5, 1.0, 2.5, 4.0):
                line = Line([-9.0, y, 0], [9.0, y, 0], color=accent, stroke_width=0.7)
                line.set_opacity(0.055)
                grid.add(line)
        elif environment == "document_space":
            for x in (-6.0, -3.0, 0.0, 3.0, 6.0):
                sheet = RoundedRectangle(
                    width=2.2, height=3.0, corner_radius=0.12,
                    fill_color=panel_color, fill_opacity=0.08,
                    stroke_color=accent, stroke_width=0.8,
                ).shift(RIGHT * x + DOWN * 2.8)
                sheet.set_opacity(0.16)
                grid.add(sheet)
        elif environment == "security_boundary":
            boundary = Line(UP * 5.0, DOWN * 5.0, color=accent, stroke_width=2.0)
            boundary.set_opacity(0.12)
            grid.add(boundary)
        self.add(base, halo_left, halo_right, grid)
        self._environment_group = VGroup(base, halo_left, halo_right, grid)

    def _camera_enabled(self) -> bool:
        style = getattr(self, "_camera_style", "auto")
        return style not in {"static", "off", "none"}

    def _camera_target_width(self, mob: object, *, emphasis: float = 1.0) -> float:
        width = float(getattr(mob, "width", 4.0))
        # Deliberately mild. Educational framing should guide attention without
        # making the viewer seasick or hiding context.
        desired = max(8.4, min(11.7, width * 1.90 + 2.7))
        return max(8.2, min(self._camera_home_width, desired / max(0.85, emphasis)))

    def _camera_focus(self, mob: object | None, run_time: float, *, emphasis: float = 1.0) -> None:
        if not self._camera_enabled() or mob is None or run_time <= 0.08:
            return
        center = getattr(mob, "get_center")()
        # Keep some global context by biasing the frame toward the origin.
        framed_center = center * 0.72
        animation = self.camera.frame.animate.move_to(framed_center).set_width(
            self._camera_target_width(mob, emphasis=emphasis)
        )
        self._play(animation, min(0.34, run_time))

    def _camera_reframe_between(
        self, source: object | None, destination: object | None, run_time: float
    ) -> None:
        if not self._camera_enabled() or source is None or destination is None or run_time <= 0.08:
            return
        midpoint = (source.get_center() + destination.get_center()) / 2
        separation = abs(float(destination.get_center()[0] - source.get_center()[0]))
        width = max(9.4, min(self._camera_home_width, 9.2 + separation * 0.42))
        animation = self.camera.frame.animate.move_to(midpoint * 0.48).set_width(width)
        self._play(animation, min(0.30, run_time))

    def _camera_restore(self, run_time: float = 0.28) -> None:
        if not self._camera_enabled() or run_time <= 0.08:
            return
        frame = self.camera.frame
        if (
            abs(float(frame.width) - self._camera_home_width) < 0.05
            and sum(abs(float(v)) for v in frame.get_center()[:2]) < 0.05
        ):
            return
        self._play(
            frame.animate.move_to(self._camera_home_center).set_width(self._camera_home_width),
            run_time,
        )

    _SLOT_POSITIONS = {
        "left_top": (-3.65, 1.50, 0), "left_mid": (-3.65, 0.0, 0), "left_bottom": (-3.65, -1.55, 0),
        "center_top": (0.0, 1.50, 0), "center": (0.0, 0.0, 0), "center_bottom": (0.0, -1.55, 0),
        "right_top": (3.65, 1.50, 0), "right_mid": (3.65, 0.0, 0), "right_bottom": (3.65, -1.55, 0),
        "wide_top": (0.0, 1.25, 0), "wide_mid": (0.0, -0.05, 0), "wide_bottom": (0.0, -1.55, 0),
    }

    def _render_storyboard(self, spec: dict[str, object]) -> None:
        self._sb_objects: dict[str, object] = {}
        self._sb_kinds: dict[str, str] = {}
        self._sb_visible: set[str] = set()
        self._sb_code_lines: dict[str, list[object]] = {}
        self._sb_code_shells: dict[str, object] = {}
        self._sb_code_shell_primed: set[str] = set()
        self._sb_step_index: dict[str, int] = {}
        raw_objects = [raw for raw in spec.get("objects", []) if isinstance(raw, dict)]
        self._sb_object_count = len(raw_objects)
        self._sb_layout = str(spec.get("layout") or "freeform")
        self._learning_phase = str(spec.get("learning_phase") or "explain")
        self._sb_focus_id: str | None = None

        for raw in raw_objects:
            object_id = str(raw.get("id") or "")
            if not object_id:
                continue
            obj = self._storyboard_object(raw)
            self._sb_objects[object_id] = obj
            self._sb_kinds[object_id] = str(raw.get("kind") or "node")

        self._normalize_storyboard_layout()
        beats = [b for b in spec.get("beats", []) if isinstance(b, dict)]
        if not beats:
            for object_id in self._sb_objects:
                self._ensure_visible(object_id, 0.35)
            self.wait(max(0.0, self.total - self.spent))
            return

        # Never begin a scene on an empty dark canvas. Prime only the objects
        # referenced by the first beat, which are guaranteed to belong to this
        # narration window. The semantic action itself still occurs at its cue.
        self._prime_storyboard_canvas(beats)
        narration = str(spec.get("description") or "")
        scene_start = self.spent
        available = max(0.8, self.total - scene_start - 0.18)
        anchors = self._cue_anchors(beats, narration)
        interaction_enabled = os.getenv("STUDY_ACTIVE_CHECKS", "off").strip().lower() in {"1", "true", "yes", "on"}
        interaction_prompt = str(spec.get("interaction_prompt") or "").strip() if interaction_enabled else ""
        interaction_answer = str(spec.get("interaction_answer") or "").strip() if interaction_enabled else ""
        interaction_choices = (
            [str(v).strip() for v in spec.get("interaction_choices", []) if str(v).strip()][:3]
            if interaction_enabled else []
        )
        interaction_card = None
        question_started = None
        schedule = spec.get("beat_schedule") or []

        for index, (beat, anchor) in enumerate(zip(beats, anchors)):
            # The cue is a verbatim phrase from narration. Align the visual action
            # to that point in speech instead of spacing all animations uniformly.
            desired_start = scene_start + min(0.93, max(0.0, anchor)) * available
            if index < len(schedule):
                desired_start = float(schedule[index]["start"])
            lead_wait = desired_start - self.spent
            if lead_wait > 0.05:
                self.wait(lead_wait)
                self.spent += lead_wait

            weight = max(1, int(beat.get("weight") or 1))
            next_anchor = anchors[index + 1] if index + 1 < len(anchors) else 0.97
            next_start = (
                float(schedule[index + 1]["start"])
                if index + 1 < len(schedule) else self.total
            ) if schedule else scene_start + next_anchor * available
            cue_window = max(0.1, next_start - self.spent)
            run_time = max(0.10, min(1.65 + 0.22 * (weight - 1), cue_window * 0.62))
            self._execute_storyboard_beat(beat, run_time=run_time, beat_index=index)
            if index == 0:
                self._retire_context_title()

            # Sparse cognitive interaction for ordinary YouTube video: ask the
            # viewer to predict/recall from the scene, then reveal the answer.
            # It never replaces the narration-driven semantic beats.
            if interaction_prompt and interaction_card is None and index >= max(1, len(beats) // 2 - 1):
                interaction_card = self._viewer_check_card(interaction_prompt, answer=False, choices=interaction_choices)
                self._play(FadeIn(interaction_card, shift=UP * 0.05), min(0.42, max(0.22, run_time * 0.24)))
                question_started = self.spent
                pause = 0.0  # Do not delay semantic cues while narration continues.
                if pause > 0.16:
                    self.wait(pause)
                    self.spent += pause
            if interaction_card is not None and interaction_answer and question_started is not None and self.spent - question_started >= 3.0 and index >= max(2, len(beats) - 2):
                answer_card = self._viewer_check_card(interaction_answer, answer=True, choices=[])
                self._play(ReplacementTransform(interaction_card, answer_card), min(0.42, max(0.22, run_time * 0.24)))
                pause = min(0.52, max(0.0, self.total - self.spent - 0.38))
                if pause > 0.14:
                    self.wait(pause)
                    self.spent += pause
                interaction_card = answer_card
                interaction_answer = ""

        if interaction_card is not None and self.total - self.spent > 0.22:
            self._play(FadeOut(interaction_card, shift=DOWN * 0.03), 0.18)

        if self.total - self.spent > 0.42:
            self._camera_restore(min(0.28, self.total - self.spent - 0.08))
        if self.total - self.spent > 0.03:
            self.wait(self.total - self.spent)

    def _viewer_check_card(self, text: str, *, answer: bool, choices: list[str] | None = None) -> VGroup:
        """Mobile-readable active-learning overlay with optional choices."""
        accent = GREEN if answer else GOLD
        tag = self._label("ANSWER" if answer else "PAUSE & PREDICT", 15, accent)
        body_text = self._clean_display_text(text)
        if answer:
            body_text = f"{body_text}"
        body_lines = textwrap.wrap(body_text, width=38, break_long_words=False, break_on_hyphens=False) or [body_text]
        body = Paragraph(*body_lines[:2], font_size=22, color=WHITE, alignment="left", line_spacing=0.86)
        choice_items = [self._clean_display_text(v) for v in (choices or []) if self._clean_display_text(v)]
        choice_group = VGroup()
        if choice_items:
            rows = []
            for idx, value in enumerate(choice_items[:3]):
                row = self._label(f"{chr(65 + idx)}. {value}", 16, TEXT)
                rows.append(row)
            choice_group = VGroup(*rows).arrange(DOWN, aligned_edge=LEFT, buff=0.08)

        height = 1.62 + (0.32 * len(choice_items) if choice_items else 0.0)
        panel = RoundedRectangle(
            width=6.45,
            height=min(2.55, height),
            corner_radius=0.18,
            fill_color="#0B1B2D",
            fill_opacity=0.98,
            stroke_color=accent,
            stroke_width=2.2,
        )
        tag.next_to(panel.get_top(), DOWN, buff=0.14).align_to(panel, LEFT).shift(RIGHT * 0.22)
        body.next_to(tag, DOWN, buff=0.12).align_to(tag, LEFT)
        parts = [panel, tag, body]
        if len(choice_group) > 0:
            choice_group.next_to(body, DOWN, buff=0.12).align_to(body, LEFT)
            parts.append(choice_group)
        card = VGroup(*parts)
        card.to_edge(DOWN, buff=0.18)
        return card

    @staticmethod
    def _cue_anchors(beats: list[dict[str, object]], narration: str) -> list[float]:
        """Return monotonic 0..1 speech positions for storyboard beats."""
        text = " ".join(str(narration or "").lower().split())
        if not beats:
            return []
        if not text:
            return [(i + 0.5) / len(beats) for i in range(len(beats))]

        anchors: list[float] = []
        cursor = 0
        for i, beat in enumerate(beats):
            cue = " ".join(str(beat.get("cue") or "").lower().split())
            index = text.find(cue, cursor) if cue else -1
            if index < 0 and cue:
                index = text.find(cue)
            if index >= 0:
                fraction = index / max(1, len(text) - 1)
                cursor = index + len(cue)
            else:
                fraction = (i + 0.5) / len(beats)
            if anchors:
                fraction = max(fraction, anchors[-1] + 0.035)
            anchors.append(min(0.94, fraction))
        return anchors

    def _storyboard_object(self, raw: dict[str, object]):
        kind = str(raw.get("kind") or "node")
        label = str(raw.get("label") or kind.replace("_", " ").title())
        detail = [str(x) for x in raw.get("detail", []) if str(x).strip()]
        slot = str(raw.get("slot") or "center")
        pos = self._SLOT_POSITIONS.get(slot, self._SLOT_POSITIONS["center"])
        wide = slot.startswith("wide_")

        if kind == "text":
            mob = self._label(label, 28, WHITE)
        elif kind == "theory_point":
            # Purpose-built beginner theory card. The body comes directly from
            # the current narration window so voice and visual stay aligned.
            accent = GOLD if label.lower().startswith("definition") else (TEAL if "key" in label.lower() else BLUE)
            panel = RoundedRectangle(
                width=9.6, height=1.28, corner_radius=0.18,
                fill_color="#0A1726", fill_opacity=0.98,
                stroke_color=accent, stroke_width=2.0,
            )
            bullet = Circle(radius=0.10, color=accent, fill_color=accent, fill_opacity=1, stroke_width=0)
            bullet.move_to(panel.get_left() + RIGHT * 0.34)
            tag = self._label(label.upper(), 12, accent)
            tag.move_to(panel.get_left() + RIGHT * 1.35 + UP * 0.28).align_to(panel, LEFT).shift(RIGHT * 0.55)
            body_text = self._clean_display_text(detail[0] if detail else label)
            body_lines = textwrap.wrap(body_text, width=64, break_long_words=False, break_on_hyphens=False) or [body_text]
            body = Paragraph(*body_lines[:2], font_size=22, color=WHITE, alignment="left", line_spacing=0.82)
            if body.width > 7.95:
                body.scale_to_fit_width(7.95)
            body.move_to(panel.get_left() + RIGHT * 5.05 + DOWN * 0.13)
            mob = VGroup(panel, bullet, tag, body)
        elif kind == "agent":
            # A recurring circle made the old videos look like the same scene
            # replaying. Render an agent as a small decision workspace instead:
            # it reads as a software component while remaining visually distinct
            # from the language model and the human user.
            card = RoundedRectangle(
                width=2.85, height=1.62, corner_radius=0.18,
                fill_color="#0B2430", fill_opacity=1, stroke_color=TEAL, stroke_width=2.5,
            )
            title = self._label(label, 18, WHITE)
            if title.width > 2.35:
                title.scale_to_fit_width(2.35)
            title.move_to(card.get_top() + DOWN * 0.38)
            core = Circle(radius=0.18, color=TEAL, fill_color=TEAL, fill_opacity=1, stroke_width=0)
            core.move_to(card.get_center() + DOWN * 0.18)
            left_dot = Dot(radius=0.055, color=BLUE).move_to(core.get_center() + LEFT * 0.72)
            right_dot = Dot(radius=0.055, color=GREEN).move_to(core.get_center() + RIGHT * 0.72)
            links = VGroup(
                Line(left_dot.get_center(), core.get_center(), color=BLUE, stroke_width=1.4),
                Line(core.get_center(), right_dot.get_center(), color=GREEN, stroke_width=1.4),
            )
            mob = VGroup(card, links, left_dot, core, right_dot, title)
        elif kind == "model":
            ring = Circle(radius=0.78, color=PURPLE, fill_color=PANEL, fill_opacity=1, stroke_width=2.6)
            inner = Circle(radius=0.22, color=PURPLE, fill_color=PURPLE, fill_opacity=1, stroke_width=0).move_to(ring)
            txt = self._label(label, 16).next_to(ring, DOWN, buff=0.12)
            mob = VGroup(ring, inner, txt)
        elif kind == "user":
            head = Circle(radius=0.28, color=BLUE, fill_color="#10223A", fill_opacity=1, stroke_width=2.2)
            body = RoundedRectangle(width=1.25, height=0.82, corner_radius=0.30, color=BLUE, fill_color="#10223A", fill_opacity=1, stroke_width=2.2)
            body.next_to(head, DOWN, buff=0.08)
            txt = self._label(label, 16).next_to(body, DOWN, buff=0.12)
            mob = VGroup(head, body, txt)
        elif kind == "host":
            frame = RoundedRectangle(width=2.8 if not wide else 5.8, height=1.65, corner_radius=0.16, fill_color=PANEL, fill_opacity=1, stroke_color=PURPLE, stroke_width=2.4)
            topbar = Rectangle(width=frame.width - 0.18, height=0.26, fill_color="#241B3D", fill_opacity=1, stroke_width=0).move_to(frame.get_top() + DOWN * 0.2)
            txt = self._label(label, 19).move_to(frame.get_center() + DOWN * 0.08)
            cap = Text("HOST", font_size=11, color=PURPLE).next_to(frame.get_top(), DOWN, buff=0.05).align_to(frame, LEFT).shift(RIGHT * 0.12)
            mob = VGroup(frame, topbar, txt, cap)
        elif kind == "client":
            ring = Circle(radius=0.82, color=BLUE, fill_color="#10223A", fill_opacity=1, stroke_width=2.6)
            inner = Circle(radius=0.18, color=BLUE, fill_color=BLUE, fill_opacity=1, stroke_width=0).move_to(ring)
            txt = self._label(label, 17).next_to(ring, DOWN, buff=0.12)
            mob = VGroup(ring, inner, txt)
        elif kind == "server":
            trays = VGroup(*[RoundedRectangle(width=2.45, height=0.46, corner_radius=0.08, fill_color=PANEL, fill_opacity=1, stroke_color=TEAL, stroke_width=1.8) for _ in range(3)]).arrange(DOWN, buff=0.12)
            leds = VGroup(*[Dot(radius=0.05, color=GREEN).move_to(tray.get_right() + LEFT * 0.18) for tray in trays])
            txt = self._label(label, 16).next_to(trays, DOWN, buff=0.12)
            mob = VGroup(trays, leds, txt)
        elif kind == "tool":
            gear = VGroup(Circle(radius=0.72, color=PURPLE, fill_color="#201938", fill_opacity=1, stroke_width=2.5), Circle(radius=0.22, color=PURPLE, stroke_width=2.2))
            for angle in range(0, 360, 45):
                rad = math.radians(angle)
                gear.add(Line([0.72*math.cos(rad), 0.72*math.sin(rad), 0], [0.96*math.cos(rad), 0.96*math.sin(rad), 0], color=PURPLE, stroke_width=3))
            txt = self._label(label, 16).next_to(gear, DOWN, buff=0.12)
            mob = VGroup(gear, txt)
        elif kind == "resource":
            page = Rectangle(width=1.75, height=2.05, color=GREEN, fill_color="#102B27", fill_opacity=1, stroke_width=2.2)
            lines = VGroup(*[Line(LEFT * 0.5, RIGHT * 0.5, color=GREEN, stroke_width=1.6) for _ in range(3)]).arrange(DOWN, buff=0.2).move_to(page)
            txt = self._label(label, 15).next_to(page, DOWN, buff=0.12)
            mob = VGroup(page, lines, txt)
        elif kind == "search_ui":
            frame = RoundedRectangle(
                width=4.7 if not wide else 7.2, height=2.45, corner_radius=0.2,
                fill_color="#081522", fill_opacity=1, stroke_color=BLUE, stroke_width=2.2,
            )
            topbar = Rectangle(
                width=frame.width - 0.18, height=0.34, fill_color="#12263A",
                fill_opacity=1, stroke_width=0,
            ).move_to(frame.get_top() + DOWN * 0.25)
            field = RoundedRectangle(
                width=frame.width - 0.7, height=0.72, corner_radius=0.18,
                fill_color="#102238", fill_opacity=1, stroke_color=GOLD, stroke_width=1.7,
            ).move_to(frame.get_center() + UP * 0.18)
            query = self._label(label, 18, WHITE)
            if query.width > field.width - 0.72:
                query.scale_to_fit_width(field.width - 0.72)
            query.move_to(field.get_center() + LEFT * 0.12)
            search_ring = Circle(radius=0.11, color=GOLD, stroke_width=2.0).move_to(field.get_right() + LEFT * 0.28)
            search_handle = Line(
                search_ring.get_center() + RIGHT * 0.07 + DOWN * 0.07,
                search_ring.get_center() + RIGHT * 0.18 + DOWN * 0.18,
                color=GOLD, stroke_width=2.0,
            )
            caption = self._label("QUESTION", 11, MUTED).move_to(frame.get_bottom() + UP * 0.36)
            mob = VGroup(frame, topbar, field, query, search_ring, search_handle, caption)
        elif kind == "book":
            left_page = RoundedRectangle(
                width=1.72, height=2.15, corner_radius=0.10,
                fill_color="#F1E7CC", fill_opacity=1, stroke_color=GOLD, stroke_width=2.0,
            ).rotate(-0.10).shift(LEFT * 0.82)
            right_page = RoundedRectangle(
                width=1.72, height=2.15, corner_radius=0.10,
                fill_color="#F1E7CC", fill_opacity=1, stroke_color=GOLD, stroke_width=2.0,
            ).rotate(0.10).shift(RIGHT * 0.82)
            spine = Line(DOWN * 0.98, UP * 0.98, color="#8A6D2F", stroke_width=2.2)
            page_lines = VGroup()
            for page_x in (-0.82, 0.82):
                for y in (0.48, 0.14, -0.20, -0.54):
                    line = Line(LEFT * 0.48, RIGHT * 0.48, color="#8A7650", stroke_width=1.1)
                    line.move_to([page_x, y, 0])
                    page_lines.add(line)
            txt = self._label(label, 16, GOLD).next_to(VGroup(left_page, right_page), DOWN, buff=0.14)
            mob = VGroup(left_page, right_page, spine, page_lines, txt)
        elif kind == "context_window":
            panel = RoundedRectangle(
                width=4.45 if not wide else 7.4, height=3.05, corner_radius=0.20,
                fill_color="#111827", fill_opacity=1, stroke_color=PURPLE, stroke_width=2.3,
            )
            header = self._label(label, 17, PURPLE).move_to(panel.get_top() + DOWN * 0.28)
            query_chip = RoundedRectangle(
                width=panel.width - 0.55, height=0.54, corner_radius=0.14,
                fill_color="#33280B", fill_opacity=1, stroke_color=GOLD, stroke_width=1.3,
            ).move_to(panel.get_center() + UP * 0.52)
            query_txt = self._label("Question", 13, GOLD).move_to(query_chip)
            rows = VGroup()
            row_values = detail[:3] or ["Evidence A", "Evidence B"]
            for value in row_values:
                row = RoundedRectangle(
                    width=panel.width - 0.7, height=0.48, corner_radius=0.10,
                    fill_color="#10223A", fill_opacity=1, stroke_color=BLUE, stroke_width=1.1,
                )
                txt = self._label(value, 12, TEXT)
                if txt.width > row.width - 0.35:
                    txt.scale_to_fit_width(row.width - 0.35)
                txt.move_to(row)
                rows.add(VGroup(row, txt))
            rows.arrange(DOWN, buff=0.10).move_to(panel.get_center() + DOWN * 0.52)
            mob = VGroup(panel, header, query_chip, query_txt, rows)
        elif kind == "answer_panel":
            panel = RoundedRectangle(
                width=4.45 if not wide else 7.4, height=2.9, corner_radius=0.20,
                fill_color="#0B211D", fill_opacity=1, stroke_color=GREEN, stroke_width=2.3,
            )
            header = self._label(label, 17, GREEN).move_to(panel.get_top() + DOWN * 0.28)
            body_lines = VGroup(*[
                Line(LEFT * 1.55, RIGHT * 1.55, color=TEXT, stroke_width=2.0)
                for _ in range(3)
            ]).arrange(DOWN, buff=0.24).move_to(panel.get_center() + UP * 0.08)
            chips = VGroup()
            chip_values = detail[:2] or ["Source 1", "Source 2"]
            for value in chip_values:
                chip = RoundedRectangle(
                    width=1.35, height=0.38, corner_radius=0.12,
                    fill_color="#102B27", fill_opacity=1, stroke_color=TEAL, stroke_width=1.1,
                )
                txt = self._label(value, 10, TEAL)
                if txt.width > chip.width - 0.16:
                    txt.scale_to_fit_width(chip.width - 0.16)
                txt.move_to(chip)
                chips.add(VGroup(chip, txt))
            chips.arrange(RIGHT, buff=0.16).move_to(panel.get_bottom() + UP * 0.42)
            mob = VGroup(panel, header, body_lines, chips)
        elif kind == "point_cloud":
            x_axis = Line(LEFT * 2.15, RIGHT * 2.15, color=MUTED, stroke_width=1.6)
            y_axis = Line(DOWN * 1.45, UP * 1.45, color=MUTED, stroke_width=1.6)
            coords = [
                (-1.62, 0.85), (-1.32, 0.42), (-1.08, 1.10),
                (-0.62, -0.72), (-0.28, -0.98), (-0.04, -0.55),
                (0.72, 0.42), (0.96, 0.76), (1.26, 0.50), (1.52, 0.92),
            ]
            colors = [BLUE, BLUE, BLUE, PURPLE, PURPLE, PURPLE, TEAL, TEAL, TEAL, TEAL]
            dots = VGroup(*[
                Dot([x, y, 0], radius=0.09, color=colors[i])
                for i, (x, y) in enumerate(coords)
            ])
            focus = Circle(radius=0.28, color=GOLD, stroke_width=2.0).move_to(dots[-2])
            txt = self._label(label, 15).next_to(x_axis, DOWN, buff=0.20)
            mob = VGroup(VGroup(x_axis, y_axis), dots, focus, txt)
        elif kind == "prompt":
            bubble = RoundedRectangle(width=2.8 if not wide else 5.2, height=1.3, corner_radius=0.24, fill_color="#33280B", fill_opacity=1, stroke_color=GOLD, stroke_width=2.2)
            tail = Triangle(color=GOLD, fill_color="#33280B", fill_opacity=1).scale(0.18).rotate(-math.pi/2).next_to(bubble, DOWN, buff=-0.03).shift(LEFT * 0.65)
            txt = self._label(label, 17).move_to(bubble)
            mob = VGroup(bubble, tail, txt)
        elif kind in {"file", "document"}:
            page = Rectangle(width=1.85, height=2.2, color=BLUE, fill_color=PANEL_2, fill_opacity=1, stroke_width=2.2)
            lines = VGroup(*[Line(LEFT * 0.55, RIGHT * 0.55, color=MUTED, stroke_width=2) for _ in range(3)]).arrange(DOWN, buff=0.18).move_to(page.get_center() + DOWN * 0.15)
            txt = self._label(label, 15).next_to(page, DOWN, buff=0.12)
            mob = VGroup(page, lines, txt)
        elif kind == "folder":
            body = RoundedRectangle(width=2.35, height=1.55, corner_radius=0.12, fill_color="#172554", fill_opacity=1, stroke_color=BLUE, stroke_width=2.2)
            tab = Rectangle(width=0.85, height=0.3, fill_color="#172554", fill_opacity=1, stroke_color=BLUE, stroke_width=2.0).move_to(body.get_top() + LEFT * 0.55 + UP * 0.08)
            txt = self._label(label, 16).move_to(body)
            mob = VGroup(body, tab, txt)
        elif kind == "person":
            head = Circle(radius=0.32, color=GOLD, fill_color=PANEL, fill_opacity=1, stroke_width=2.2).shift(UP * 0.65)
            body = Line(UP * 0.28, DOWN * 0.72, color=GOLD, stroke_width=3)
            arms = Line(LEFT * 0.55 + UP * 0.02, RIGHT * 0.55 + UP * 0.02, color=GOLD, stroke_width=2.6)
            leg1 = Line(DOWN * 0.68, LEFT * 0.42 + DOWN * 1.25, color=GOLD, stroke_width=2.6)
            leg2 = Line(DOWN * 0.68, RIGHT * 0.42 + DOWN * 1.25, color=GOLD, stroke_width=2.6)
            txt = self._label(label, 16).next_to(VGroup(head, body, arms, leg1, leg2), DOWN, buff=0.12)
            mob = VGroup(head, body, arms, leg1, leg2, txt)
        elif kind == "place":
            building = RoundedRectangle(width=2.45, height=1.55, corner_radius=0.08, fill_color=PANEL, fill_opacity=1, stroke_color=GOLD, stroke_width=2.2)
            roof = Triangle(color=GOLD, fill_color="#3A2A0A", fill_opacity=1).scale(0.75).stretch_to_fit_width(2.55).stretch_to_fit_height(0.7).next_to(building, UP, buff=-0.08)
            door = Rectangle(width=0.45, height=0.72, fill_color="#1E293B", fill_opacity=1, stroke_color=GOLD, stroke_width=1.4).move_to(building.get_bottom() + UP * 0.36)
            txt = self._label(label, 16).next_to(building, DOWN, buff=0.12)
            mob = VGroup(building, roof, door, txt)
        elif kind in {"database", "vector_store"}:
            color = PURPLE if kind == "vector_store" else BLUE
            body = RoundedRectangle(width=2.25, height=1.75, corner_radius=0.22, fill_color=PANEL, fill_opacity=1, stroke_color=color, stroke_width=2.4)
            stripes = VGroup(*[Line(LEFT * 0.78, RIGHT * 0.78, color=color, stroke_width=1.8) for _ in range(3)]).arrange(DOWN, buff=0.28).move_to(body)
            txt = self._label(label, 16).next_to(body, DOWN, buff=0.12)
            mob = VGroup(body, stripes, txt)
        elif kind == "device":
            phone = RoundedRectangle(width=1.75, height=3.15, corner_radius=0.26, fill_color="#0F2034", fill_opacity=1, stroke_color=BLUE, stroke_width=2.6)
            screen = RoundedRectangle(width=1.48, height=2.45, corner_radius=0.15, fill_color="#132A44", fill_opacity=1, stroke_color="#52677F", stroke_width=1.3).move_to(phone.get_center() + UP * 0.08)
            dot = Circle(radius=0.08, color=MUTED, fill_color=MUTED, fill_opacity=1).move_to(phone.get_bottom() + UP * 0.22)
            txt = self._label(label, 17).next_to(phone, DOWN, buff=0.12)
            mob = VGroup(phone, screen, dot, txt)
        elif kind == "app":
            tile = RoundedRectangle(width=2.1, height=2.1, corner_radius=0.38, fill_color="#1A2740", fill_opacity=1, stroke_color=PURPLE, stroke_width=2.5)
            glyph = Square(side_length=0.72, color=PURPLE, fill_color="#2B2148", fill_opacity=1, stroke_width=2).rotate(math.pi/4).move_to(tile)
            txt = self._label(label, 17).next_to(tile, DOWN, buff=0.12)
            mob = VGroup(tile, glyph, txt)
        elif kind == "sensor":
            core = Circle(radius=0.38, color=GOLD, fill_color="#33280B", fill_opacity=1, stroke_width=2.5)
            waves = VGroup(*[Circle(radius=r, color=GOLD, stroke_width=1.8).set_opacity(0.85 - i*0.18) for i, r in enumerate((0.72, 1.05, 1.38))])
            txt = self._label(label, 17).next_to(waves, DOWN, buff=0.12)
            mob = VGroup(waves, core, txt)
        elif kind == "browser":
            frame = RoundedRectangle(width=4.2 if not wide else 7.0, height=2.65, corner_radius=0.18, fill_color=PANEL, fill_opacity=1, stroke_color=BLUE, stroke_width=2.2)
            bar = Rectangle(width=frame.width - 0.25, height=0.35, fill_color="#1E293B", fill_opacity=1, stroke_width=0).move_to(frame.get_top() + DOWN * 0.28)
            txt = self._label(label, 18).move_to(frame.get_center() + DOWN * 0.12)
            mob = VGroup(frame, bar, txt)
        elif kind == "terminal":
            frame = RoundedRectangle(width=4.0 if not wide else 7.0, height=2.35, corner_radius=0.16, fill_color="#060B13", fill_opacity=1, stroke_color=GREEN, stroke_width=2.0)
            prompt = self._code_text("> " + label, 17, GREEN)
            if prompt.width > frame.width - 0.4:
                prompt.scale_to_fit_width(frame.width - 0.4)
            prompt.move_to(frame.get_center())
            mob = VGroup(frame, prompt)
        elif kind == "code":
            # Build code from portable Pango Text primitives instead of relying
            # on Manim's Code internals. This gives us stable line-level reveal
            # and highlighting on macOS/Linux/Windows.
            width = 7.15 if not wide else 10.5
            content = detail[:6] or [
                "request = parse(message)",
                "validate(request)",
                "result = execute(request)",
                "return result",
            ]
            panel_height = min(4.45, max(2.75, 1.35 + 0.58 * len(content)))
            panel = RoundedRectangle(
                width=width, height=panel_height, corner_radius=0.18,
                fill_color="#050A12", fill_opacity=1,
                stroke_color="#3B556C", stroke_width=2.0,
            )
            topbar = Rectangle(
                width=width - 0.04, height=0.46, fill_color="#0D1724",
                fill_opacity=1, stroke_width=0,
            ).move_to(panel.get_top() + DOWN * 0.25)
            lights = VGroup(
                Dot(radius=0.055, color=RED),
                Dot(radius=0.055, color=GOLD),
                Dot(radius=0.055, color=GREEN),
            ).arrange(RIGHT, buff=0.11)
            lights.move_to(topbar.get_left() + RIGHT * 0.38)
            title = self._label(label, 16, TEAL)
            if title.width > width * 0.48:
                title.scale_to_fit_width(width * 0.48)
            title.move_to(topbar.get_center())

            lines: list[object] = []
            for i, line_text in enumerate(content, start=1):
                code_color = GREEN if re.match(r"\s*(return|assert|verify)", line_text) else TEXT
                line = self._code_text(f"{i:>2}  {line_text}", 22, code_color)
                if line.width > width - 0.58:
                    line.scale_to_fit_width(width - 0.58)
                lines.append(line)
            code_lines = VGroup(*lines).arrange(DOWN, aligned_edge=LEFT, buff=0.17)
            code_lines.move_to(panel.get_center() + DOWN * 0.13)
            code_lines.align_to(panel, LEFT).shift(RIGHT * 0.28)
            shell = VGroup(panel, topbar, lights, title)
            mob = VGroup(shell, code_lines)
            object_id = str(raw.get("id"))
            self._sb_code_shells[object_id] = shell
            self._sb_code_lines[object_id] = list(lines)
        elif kind in {"api", "function"}:
            color = BLUE if kind == "api" else PURPLE
            cap_text = "API" if kind == "api" else "ƒ(x)"
            box = RoundedRectangle(width=2.6, height=1.15, corner_radius=0.18, fill_color=PANEL, fill_opacity=1, stroke_color=color, stroke_width=2.3)
            cap = Text(cap_text, font_size=18, color=color).move_to(box.get_center() + UP * 0.18)
            txt = self._label(label, 14, TEXT).move_to(box.get_center() + DOWN * 0.22)
            mob = VGroup(box, cap, txt)
        elif kind == "connector":
            line = Line(LEFT * 0.8, RIGHT * 0.8, color=TEAL, stroke_width=4)
            left_dot = Dot(line.get_start(), color=BLUE, radius=0.11)
            right_dot = Dot(line.get_end(), color=GREEN, radius=0.11)
            txt = self._label(label, 15).next_to(line, DOWN, buff=0.16)
            mob = VGroup(line, left_dot, right_dot, txt)
        elif kind == "lock":
            body = RoundedRectangle(width=1.2, height=0.9, corner_radius=0.14, fill_color="#102B27", fill_opacity=1, stroke_color=GREEN, stroke_width=2.5).shift(DOWN * 0.18)
            shackle = Circle(radius=0.42, color=GREEN, stroke_width=2.5).shift(UP * 0.42)
            cover = Rectangle(width=1.1, height=0.55, fill_color=BG, fill_opacity=1, stroke_width=0).move_to(shackle.get_bottom() + UP * 0.02)
            txt = self._label(label, 15).next_to(body, DOWN, buff=0.12)
            mob = VGroup(shackle, cover, body, txt)
        elif kind == "array":
            values = detail[:8] or [v.strip() for v in re.split(r"[,| ]+", label) if v.strip()][:8] or ["0", "1", "2", "3"]
            cells = VGroup(*[self._node(v, BLUE, 1.15, 0.72) for v in values]).arrange(RIGHT, buff=0.09)
            caption = self._label(label if detail else "Array", 15, MUTED).next_to(cells, DOWN, buff=0.12)
            mob = VGroup(cells, caption)
        elif kind == "packet":
            mob = self._pill(label, GOLD)
        elif kind == "shield":
            ring = Circle(radius=0.72, color=GREEN, fill_color="#102B27", fill_opacity=1, stroke_width=3)
            mark = Text("✓", font_size=36, color=GREEN).move_to(ring)
            txt = self._label(label, 15).next_to(ring, DOWN, buff=0.1)
            mob = VGroup(ring, mark, txt)
        elif kind == "gate":
            bar = Line(UP * 1.05, DOWN * 1.05, color=GOLD, stroke_width=6)
            txt = self._label(label, 16, GOLD).next_to(bar, UP, buff=0.12)
            mob = VGroup(bar, txt)
        elif kind == "table":
            cells = VGroup()
            for r in range(3):
                for c in range(4):
                    cells.add(Rectangle(width=0.85, height=0.48, stroke_color="#64748B", stroke_width=1.2, fill_color=PANEL, fill_opacity=1).shift(RIGHT * (c - 1.5) * 0.85 + DOWN * (r - 1) * 0.48))
            txt = self._label(label, 15).next_to(cells, DOWN, buff=0.12)
            mob = VGroup(cells, txt)
        elif kind == "equation":
            formula = detail[0] if detail else label
            eq = self._code_text(formula, 34, GOLD)
            if eq.width > (8.8 if wide else 5.8):
                eq.scale_to_fit_width(8.8 if wide else 5.8)
            caption = self._label(label, 15, MUTED).next_to(eq, DOWN, buff=0.18) if detail else None
            mob = VGroup(eq, caption) if caption is not None else VGroup(eq)
        elif kind == "number_line":
            axis = Line(LEFT * 2.7, RIGHT * 2.7, color=TEXT, stroke_width=3)
            ticks = VGroup(*[Line(UP * 0.14, DOWN * 0.14, color=MUTED, stroke_width=2).shift(RIGHT * x) for x in (-2, -1, 0, 1, 2)])
            marker_dot = Dot(color=GOLD, radius=0.1).move_to(axis.get_center())
            txt = self._label(label, 15).next_to(axis, DOWN, buff=0.2)
            mob = VGroup(axis, ticks, marker_dot, txt)
        elif kind == "graph":
            x_axis = Line(LEFT * 2.6, RIGHT * 2.6, color=MUTED, stroke_width=2)
            y_axis = Line(DOWN * 1.65, UP * 1.65, color=MUTED, stroke_width=2)
            pts = [[-2.1,-1.0,0],[-1.2,-0.35,0],[-0.3,0.1,0],[0.6,0.85,0],[1.65,1.15,0],[2.15,0.55,0]]
            curve = VGroup(*[Line(pts[i], pts[i+1], color=TEAL, stroke_width=4) for i in range(len(pts)-1)])
            txt = self._label(label, 15).next_to(x_axis, DOWN, buff=0.22)
            mob = VGroup(x_axis, y_axis, curve, txt)
        elif kind == "chart":
            heights = [0.7, 1.3, 1.9, 1.1]
            bars = VGroup(*[Rectangle(width=0.58, height=h, fill_color=[BLUE, TEAL, PURPLE, GREEN][i], fill_opacity=0.75, stroke_width=0) for i,h in enumerate(heights)]).arrange(RIGHT, buff=0.22, aligned_edge=DOWN)
            base = Line(LEFT * 1.8, RIGHT * 1.8, color=MUTED, stroke_width=2).next_to(bars, DOWN, buff=0.03)
            txt = self._label(label, 15).next_to(base, DOWN, buff=0.16)
            mob = VGroup(bars, base, txt)
        elif kind == "shape":
            lower_label = label.lower()
            if "triangle" in lower_label:
                shape = Triangle(color=TEAL, fill_color="#12352F", fill_opacity=0.65).scale(1.05)
            elif "circle" in lower_label:
                shape = Circle(radius=1.0, color=TEAL, fill_color="#12352F", fill_opacity=0.5)
            else:
                shape = Square(side_length=1.8, color=TEAL, fill_color="#12352F", fill_opacity=0.5)
            txt = self._label(label, 15).next_to(shape, DOWN, buff=0.14)
            mob = VGroup(shape, txt)
        elif kind == "quantity":
            value = detail[0] if detail else label
            big = self._code_text(value, 38, TEAL)
            txt = self._label(label, 14, MUTED).next_to(big, DOWN, buff=0.16) if detail else None
            mob = VGroup(big, txt) if txt is not None else VGroup(big)
        elif kind == "vector":
            arrow = Arrow(LEFT * 1.6 + DOWN * 0.8, RIGHT * 1.5 + UP * 1.0, buff=0.0, color=GOLD, stroke_width=5)
            txt = self._label(label, 15).next_to(arrow, DOWN, buff=0.18)
            mob = VGroup(arrow, txt)
        elif kind == "atom":
            nucleus = Circle(radius=0.28, color=GOLD, fill_color=GOLD, fill_opacity=1)
            orbit1 = Circle(radius=0.9, color=BLUE, stroke_width=1.7).stretch(1.5, 0)
            orbit2 = Circle(radius=0.9, color=PURPLE, stroke_width=1.7).stretch(1.5, 0).rotate(math.pi/3)
            e1 = Dot([1.35, 0.0, 0], color=TEAL, radius=0.08)
            e2 = Dot([-0.68, -1.02, 0], color=TEAL, radius=0.08)
            txt = self._label(label, 15).next_to(VGroup(orbit1, orbit2), DOWN, buff=0.12)
            mob = VGroup(orbit1, orbit2, nucleus, e1, e2, txt)
        elif kind == "molecule":
            a = Circle(radius=0.42, color=BLUE, fill_color="#10223A", fill_opacity=1).shift(LEFT * 0.85)
            b = Circle(radius=0.58, color=GOLD, fill_color="#33280B", fill_opacity=1)
            c = Circle(radius=0.42, color=BLUE, fill_color="#10223A", fill_opacity=1).shift(RIGHT * 0.85)
            bonds = VGroup(Line(a.get_right(), b.get_left(), color=TEXT, stroke_width=3), Line(b.get_right(), c.get_left(), color=TEXT, stroke_width=3))
            txt = self._label(label, 15).next_to(VGroup(a,b,c), DOWN, buff=0.14)
            mob = VGroup(bonds, a, b, c, txt)
        elif kind == "wave":
            pts = []
            for i in range(25):
                x = -2.6 + i * (5.2 / 24)
                y = 0.72 * math.sin((x + 2.6) * 2.25)
                pts.append([x, y, 0])
            wave = VGroup(*[Line(pts[i], pts[i+1], color=BLUE, stroke_width=3.4) for i in range(len(pts)-1)])
            txt = self._label(label, 15).next_to(wave, DOWN, buff=0.18)
            mob = VGroup(wave, txt)
        elif kind == "experiment":
            vessel = Rectangle(width=1.7, height=2.1, color=TEAL, stroke_width=2.2)
            liquid = Rectangle(width=1.58, height=0.75, fill_color=BLUE, fill_opacity=0.45, stroke_width=0).move_to(vessel.get_bottom() + UP * 0.39)
            probe = Line(UP * 1.3, DOWN * 0.5, color=GOLD, stroke_width=3).shift(RIGHT * 0.35)
            txt = self._label(label, 15).next_to(vessel, DOWN, buff=0.14)
            mob = VGroup(vessel, liquid, probe, txt)
        elif kind == "balance":
            beam = Line(LEFT * 1.5, RIGHT * 1.5, color=GOLD, stroke_width=5)
            pivot = Triangle(color=GOLD, fill_color=GOLD, fill_opacity=1).scale(0.22).rotate(3.14159).next_to(beam, DOWN, buff=0.02)
            txt = self._label(label, 16).next_to(beam, UP, buff=0.18)
            mob = VGroup(beam, pivot, txt)
        else:  # node / badge and safe fallback
            color = GREEN if kind == "badge" else TEAL
            mob = self._node(label, color, 2.4 if not wide else 5.2, 0.86)

        mob.move_to(pos)
        # Mobile-first visual hierarchy: scenes with only a few objects should
        # actually use the 1080p canvas instead of floating tiny cards in space.
        count = max(1, int(getattr(self, "_sb_object_count", 4)))
        scale = 1.76 if count <= 3 else 1.58 if count <= 5 else 1.38 if count <= 7 else 1.18
        if wide:
            scale = min(scale, 1.16)
        mob.scale(scale)
        large_kind = kind in {"code", "browser", "terminal", "table", "graph", "chart", "number_line", "equation"}
        max_width = 10.9 if wide else (8.8 if large_kind else 7.0)
        if mob.width > max_width:
            mob.scale_to_fit_width(max_width)
        if mob.height > 4.55:
            mob.scale_to_fit_height(4.55)
        return mob

    def _normalize_storyboard_layout(self) -> None:
        """Apply mobile-first geometry after semantic objects are built.

        LLM slots are hints, not pixel-perfect layout. Specialized study scenes
        get deterministic geometry so code is readable and analogy/security
        diagrams use the canvas instead of floating as tiny cards.
        """
        layout = getattr(self, "_sb_layout", "freeform")
        objects = getattr(self, "_sb_objects", {})
        kinds = getattr(self, "_sb_kinds", {})
        if not objects:
            return

        # EXPLAIN scenes intentionally look different from process diagrams:
        # one large focal concept plus supporting relationships. The next FLOW
        # scene will reorganize the same chapter into a left-to-right mechanism.
        if getattr(self, "_learning_phase", "") == "explain":
            ordered = list(objects)
            theory_ids = [oid for oid in ordered if kinds.get(oid) == "theory_point"]
            if theory_ids:
                # A theory scene should read like a clean teaching board, not a
                # system diagram. Reveal three points in the same order as the
                # narration, then hand off to the next FLOW scene.
                ys = [1.55, 0.02, -1.51]
                for oid, y in zip(theory_ids[:3], ys):
                    mob = objects[oid]
                    if mob.width > 10.2:
                        mob.scale_to_fit_width(10.2)
                    mob.move_to([0.0, y, 0])
                return

            # Legacy fallback for old cached storyboards.
            primary = objects[ordered[0]]
            if primary.width < 3.2:
                primary.scale(min(1.45, 3.2 / max(0.1, primary.width)))
            if primary.width > 5.2:
                primary.scale_to_fit_width(5.2)
            primary.move_to([-3.1, -0.05, 0])
            supports = ordered[1:4]
            ys = [1.65, -0.05, -1.75]
            for oid, y in zip(supports, ys):
                mob = objects[oid]
                if mob.width < 2.2:
                    mob.scale(min(1.25, 2.2 / max(0.1, mob.width)))
                if mob.width > 4.2:
                    mob.scale_to_fit_width(4.2)
                mob.move_to([3.55, y, 0])
            return

        if layout == "code_plus_state":
            code_ids = [oid for oid, kind in kinds.items() if kind == "code"]
            if code_ids:
                code = objects[code_ids[0]]
                if code.width < 8.0:
                    code.scale(min(1.35, 8.0 / max(0.1, code.width)))
                if code.width > 8.8:
                    code.scale_to_fit_width(8.8)
                code.move_to([-1.55, -0.10, 0])
                others = [oid for oid in objects if oid not in code_ids]
                ys = [1.65, 0.05, -1.55, 2.35, -2.25]
                for oid, y in zip(others, ys):
                    mob = objects[oid]
                    if mob.width > 2.65:
                        mob.scale_to_fit_width(2.65)
                    mob.move_to([4.55, y, 0])
                return

        if layout == "browser_demo":
            primary_ids = [oid for oid, kind in kinds.items() if kind in {"search_ui", "browser"}]
            primary = primary_ids[0] if primary_ids else next(iter(objects))
            main = objects[primary]
            if main.width > 7.4:
                main.scale_to_fit_width(7.4)
            main.move_to([-2.7, 0.0, 0])
            others = [oid for oid in objects if oid != primary]
            ys = [2.0, 0.0, -2.0, 1.15, -1.15]
            for oid, y in zip(others, ys):
                mob = objects[oid]
                max_w = 4.2 if kinds.get(oid) in {"context_window", "answer_panel", "point_cloud"} else 2.9
                if mob.width > max_w:
                    mob.scale_to_fit_width(max_w)
                mob.move_to([4.35, y, 0])
            return

        if layout == "left_to_right":
            ordered = list(objects)
            n = len(ordered)
            xs = {
                3: [-4.5, 0.0, 4.5],
                4: [-5.2, -1.75, 1.75, 5.2],
                5: [-5.4, -2.7, 0.0, 2.7, 5.4],
            }.get(n)
            if xs is None:
                xs = [(-5.4 + 10.8 * i / max(1, n - 1)) for i in range(n)]
            for i, (oid, x) in enumerate(zip(ordered, xs)):
                mob = objects[oid]
                max_w = 3.2 if kinds.get(oid) in {"point_cloud", "context_window", "answer_panel"} else 2.55
                if mob.width > max_w:
                    mob.scale_to_fit_width(max_w)
                y = 0.38 if i % 2 == 0 and n >= 4 else (-0.38 if n >= 4 else 0.0)
                mob.move_to([x, y, 0])
            return

        if layout == "timeline":
            ordered = list(objects)
            n = len(ordered)
            xs = [(-5.1 + 10.2 * i / max(1, n - 1)) for i in range(n)]
            for i, (oid, x) in enumerate(zip(ordered, xs)):
                mob = objects[oid]
                if mob.width > 2.35:
                    mob.scale_to_fit_width(2.35)
                mob.move_to([x, -0.15 if i % 2 == 0 else 0.45, 0])
            return

        if layout == "split":
            ordered = list(objects)
            cut = max(1, (len(ordered) + 1) // 2)
            left_ids, right_ids = ordered[:cut], ordered[cut:]
            def _place_column(ids, x):
                if not ids:
                    return
                ys = [0.0] if len(ids) == 1 else ([1.55, -1.55] if len(ids) == 2 else [2.15, 0.0, -2.15, 2.75, -2.75])
                for oid, y in zip(ids, ys):
                    mob = objects[oid]
                    max_w = 4.8 if kinds.get(oid) in {"context_window", "answer_panel", "point_cloud", "search_ui"} else 3.15
                    if mob.width > max_w:
                        mob.scale_to_fit_width(max_w)
                    mob.move_to([x, y, 0])
            _place_column(left_ids, -3.65)
            _place_column(right_ids, 3.65)
            return

        if layout == "table_focus":
            table_ids = [oid for oid, kind in kinds.items() if kind in {"table", "chart", "point_cloud"}]
            focus = table_ids[0] if table_ids else next(iter(objects))
            main = objects[focus]
            if main.width > 7.8:
                main.scale_to_fit_width(7.8)
            main.move_to([0.0, -0.2, 0])
            others = [oid for oid in objects if oid != focus]
            for oid, x in zip(others, [-4.8, 4.8, -3.0, 3.0]):
                mob = objects[oid]
                if mob.width > 2.55:
                    mob.scale_to_fit_width(2.55)
                mob.move_to([x, 2.3, 0])
            return

        if layout == "array_trace":
            array_ids = [oid for oid, kind in kinds.items() if kind in {"array", "point_cloud"}]
            focus = array_ids[0] if array_ids else next(iter(objects))
            main = objects[focus]
            if main.width > 8.4:
                main.scale_to_fit_width(8.4)
            main.move_to([0.0, 0.1, 0])
            others = [oid for oid in objects if oid != focus]
            for oid, pos in zip(others, [(-4.5, 2.4), (4.5, 2.4), (-4.5, -2.3), (4.5, -2.3)]):
                mob = objects[oid]
                if mob.width > 2.55:
                    mob.scale_to_fit_width(2.55)
                mob.move_to([pos[0], pos[1], 0])
            return

        if layout == "analogy_map":
            real_kinds = {"person", "place", "device", "sensor", "app", "file", "folder", "document", "book", "user"}
            real = [oid for oid, kind in kinds.items() if kind in real_kinds]
            tech = [oid for oid in objects if oid not in real]
            for group, x in ((real, -3.75), (tech, 3.75)):
                if not group:
                    continue
                if len(group) == 1:
                    ys = [0.0]
                elif len(group) == 2:
                    ys = [1.25, -1.25]
                else:
                    ys = [1.8, 0.0, -1.8, 2.5, -2.5]
                for oid, y in zip(group, ys):
                    objects[oid].move_to([x, y, 0])
            return

        if layout == "boundary":
            gate_ids = [oid for oid, kind in kinds.items() if kind in {"gate", "shield", "lock"}]
            if gate_ids:
                objects[gate_ids[0]].move_to([0.0, 0.0, 0])
                remaining = [oid for oid in objects if oid not in gate_ids]
                left = remaining[:2]
                right = remaining[2:]
                for oid, y in zip(left, [1.2, -1.2]):
                    objects[oid].move_to([-4.0, y, 0])
                for oid, y in zip(right, [1.2, -1.2, 0.0]):
                    objects[oid].move_to([4.0, y, 0])

    def _prime_storyboard_canvas(self, beats: list[dict[str, object]]) -> None:
        """Record a meaningful first frame without previewing a later scene.

        Only first-beat participants are shown. This removes black/near-empty
        bridges at scene boundaries while preserving temporal semantic locking.
        """
        if not beats:
            return
        first = beats[0]
        ids: list[str] = []
        # Establish the relationship, not just one isolated card. Showing the
        # first two beat participants at reduced opacity gives viewers spatial
        # context before the semantic action starts, without dumping the scene.
        for preview_beat in beats[:2]:
            for field in ("source", "target", "destination"):
                oid = str(preview_beat.get(field) or "")
                if oid and oid in self._sb_objects and oid not in ids:
                    ids.append(oid)
        if not ids and self._sb_objects:
            ids.append(next(iter(self._sb_objects)))
        first_action = str(first.get("action") or "")
        for oid in ids[:3]:
            if first_action == "type_code" and self._sb_kinds.get(oid) == "code":
                shell = self._sb_code_shells.get(oid)
                if shell is not None:
                    shell.set_opacity(0.88)
                    self.add(shell)
                    self._sb_code_shell_primed.add(oid)
                continue
            mob = self._sb_objects[oid]
            mob.set_opacity(0.62 if oid != ids[0] else 0.90)
            self.add(mob)
            self._sb_visible.add(oid)
        hold = min(0.12, max(0.0, self.total - self.spent - 0.2))
        if hold > 0.02:
            self.wait(hold)
            self.spent += hold

    def _ensure_visible(self, object_id: str, run_time: float = 0.35) -> None:
        if object_id in self._sb_visible:
            return
        mob = self._sb_objects.get(object_id)
        if mob is None:
            return
        self._play(FadeIn(mob, shift=UP * 0.06), run_time)
        self._sb_visible.add(object_id)

    def _focus_storyboard_object(self, object_id: str, run_time: float = 0.3) -> None:
        """Create visual hierarchy by dimming secondary objects, not shrinking them."""
        target = self._sb_objects.get(object_id)
        if target is None:
            return
        animations = []
        for oid in self._sb_visible:
            mob = self._sb_objects.get(oid)
            if mob is None:
                continue
            animations.append(mob.animate.set_opacity(1.0 if oid == object_id else 0.76))
        if animations:
            self._play(AnimationGroup(*animations, lag_ratio=0.0), min(0.28, run_time))
        self._sb_focus_id = object_id

    def _restore_storyboard_opacity(self, run_time: float = 0.22) -> None:
        if getattr(self, "_sb_focus_id", None) is None:
            return
        animations = []
        for oid in self._sb_visible:
            mob = self._sb_objects.get(oid)
            if mob is not None:
                animations.append(mob.animate.set_opacity(1.0))
        if animations:
            self._play(AnimationGroup(*animations, lag_ratio=0.0), run_time)
        self._sb_focus_id = None

    def _semantic_payload_label(self, source_id: str, target_id: str, action: str) -> str:
        """Name moving information by meaning; never show a generic `data` pill."""
        kind = self._sb_kinds.get(source_id) or self._sb_kinds.get(target_id) or ""
        labels = {
            "search_ui": "question", "prompt": "question", "user": "question",
            "document": "evidence", "file": "evidence", "book": "source",
            "vector": "vector", "point_cloud": "match", "vector_store": "retrieval",
            "context_window": "context", "answer_panel": "answer", "resource": "result",
            "code": "result", "function": "result", "api": "request", "packet": "request",
        }
        if action == "return" and kind not in {"answer_panel", "resource"}:
            return "result"
        return labels.get(kind, "request" if action == "send" else "result")

    def _execute_storyboard_beat(self, beat: dict[str, object], *, run_time: float, beat_index: int) -> None:
        action = str(beat.get("action") or "reveal")
        target_id = str(beat.get("target") or "")
        source_id = str(beat.get("source") or "")
        destination_id = str(beat.get("destination") or "")
        target = self._sb_objects.get(target_id)
        source = self._sb_objects.get(source_id)
        destination = self._sb_objects.get(destination_id)

        if action in {"reveal", "write"}:
            if target_id in self._sb_visible or target is None:
                if target is not None:
                    self._camera_focus(target, min(0.18, run_time * 0.25))
                    self._play(Circumscribe(target, color=TEAL, fade_out=True), min(run_time, 0.56))
                return
            animation = (
                Write(target)
                if action == "write" and self._sb_kinds.get(target_id) == "text"
                else FadeIn(target, shift=UP * 0.08)
            )
            self._play(animation, max(0.24, run_time * 0.72))
            self._sb_visible.add(target_id)
            if self._camera_style in {"focus", "cinematic"}:
                self._camera_focus(target, min(0.20, run_time * 0.22))
            return

        if action == "type_code":
            if target is None:
                return
            self._camera_focus(target, min(0.22, run_time * 0.20), emphasis=1.06)
            shell = self._sb_code_shells.get(target_id)
            lines = self._sb_code_lines.get(target_id, [])
            if target_id not in self._sb_visible and shell is not None and lines:
                if target_id not in self._sb_code_shell_primed:
                    self._play(FadeIn(shell, shift=UP * 0.04), max(0.18, run_time * 0.22))
                remaining = max(0.28, run_time * 0.64)
                self._play(
                    LaggedStart(*[Write(line) for line in lines], lag_ratio=0.13),
                    remaining,
                )
                self._sb_visible.add(target_id)
                return
            self._ensure_visible(target_id, min(0.3, run_time * 0.3))
            self._play(Circumscribe(target, color=TEAL, fade_out=True), max(0.28, run_time * 0.5))
            return

        if action == "connect":
            self._restore_storyboard_opacity(0.12)
            self._ensure_visible(source_id, min(0.24, run_time * 0.20))
            self._ensure_visible(destination_id, min(0.24, run_time * 0.20))
            if source is not None and destination is not None:
                self._camera_reframe_between(source, destination, min(0.22, run_time * 0.18))
                arrow = Arrow(
                    source.get_center(), destination.get_center(), buff=0.75,
                    color=TEAL, stroke_width=2.6,
                )
                self._play(GrowArrow(arrow), max(0.30, run_time * 0.58))
            return

        if action in {"move", "send", "return"}:
            self._restore_storyboard_opacity(0.10)
            self._ensure_visible(source_id, min(0.20, run_time * 0.15))
            self._ensure_visible(destination_id, min(0.20, run_time * 0.15))
            if source is None or destination is None:
                return
            moving = (
                target
                if self._sb_kinds.get(target_id) == "packet" and target is not None
                else self._pill(str(beat.get("label") or self._semantic_payload_label(source_id, target_id, action)), GOLD)
            )
            if target_id not in self._sb_visible or moving is not target:
                moving.move_to(source.get_center())
                self.add(moving)
                if moving is target:
                    self._sb_visible.add(target_id)
            direction_color = GREEN if action == "return" else TEAL
            self._camera_reframe_between(source, destination, min(0.20, run_time * 0.16))
            path_arrow = Arrow(
                source.get_center(), destination.get_center(), buff=0.72,
                color=direction_color, stroke_width=2.4,
            )
            self._play(GrowArrow(path_arrow), min(0.25, run_time * 0.20))
            path = Line(source.get_center(), destination.get_center())
            travel = MoveAlongPath(moving, path)
            if self._camera_enabled() and self._camera_style in {"auto", "follow", "cinematic"}:
                follow = self.camera.frame.animate.move_to(destination.get_center() * 0.52).set_width(
                    max(9.6, min(self._camera_home_width, 10.9))
                )
                self._play(AnimationGroup(travel, follow, lag_ratio=0.0), max(0.34, run_time * 0.55))
            else:
                self._play(travel, max(0.34, run_time * 0.55))
            self._play(FadeOut(path_arrow), min(0.14, run_time * 0.10))
            return

        if action in {"highlight", "focus", "select"}:
            self._ensure_visible(target_id, min(0.24, run_time * 0.22))
            if target is not None:
                self._camera_focus(
                    target, min(0.20, run_time * 0.18),
                    emphasis=1.06 if action == "select" else 1.0,
                )
                self._focus_storyboard_object(target_id, min(0.22, run_time * 0.2))
                self._play(
                    Circumscribe(
                        target, color=GOLD if action == "select" else TEAL,
                        fade_out=True,
                    ),
                    max(0.30, run_time * 0.52),
                )
            return

        if action == "step_code":
            self._ensure_visible(target_id, min(0.24, run_time * 0.2))
            self._camera_focus(target, min(0.20, run_time * 0.18), emphasis=1.08)
            self._focus_storyboard_object(target_id, min(0.18, run_time * 0.15))
            lines = self._sb_code_lines.get(target_id, [])
            if lines:
                index = self._sb_step_index.get(target_id, 0) % len(lines)
                self._sb_step_index[target_id] = index + 1
                active = lines[index]
                opacity_anims = [
                    line.animate.set_opacity(1.0 if i == index else 0.42)
                    for i, line in enumerate(lines)
                ]
                self._play(
                    AnimationGroup(*opacity_anims, lag_ratio=0.0),
                    min(0.18, run_time * 0.16),
                )
                self._play(
                    Circumscribe(active, color=GOLD, buff=0.06, fade_out=True),
                    max(0.30, run_time * 0.50),
                )
            elif target is not None:
                self._play(Indicate(target, color=GOLD), max(0.30, run_time * 0.65))
            return

        if action == "split":
            self._restore_storyboard_opacity(0.10)
            self._ensure_visible(source_id, min(0.24, run_time * 0.18))
            if source is None or target is None:
                self._ensure_visible(target_id, run_time)
                return
            self._camera_reframe_between(source, target, min(0.22, run_time * 0.16))
            target_kind = self._sb_kinds.get(target_id)
            if target_kind == "array" and len(target) >= 1:
                cells = target[0]
                pieces = list(cells) if hasattr(cells, "__iter__") else []
                if pieces:
                    self._play(
                        LaggedStart(
                            *[TransformFromCopy(source, piece) for piece in pieces],
                            lag_ratio=0.16,
                        ),
                        max(0.45, run_time * 0.68),
                    )
                    if len(target) > 1:
                        self._play(FadeIn(target[1], shift=UP * 0.04), min(0.20, run_time * 0.16))
                    self._sb_visible.add(target_id)
                    return
            self._play(TransformFromCopy(source, target), max(0.40, run_time * 0.72))
            self._sb_visible.add(target_id)
            return

        if action == "scan":
            self._ensure_visible(source_id, min(0.18, run_time * 0.12))
            self._ensure_visible(target_id, min(0.24, run_time * 0.18))
            if target is None:
                return
            self._camera_focus(target, min(0.20, run_time * 0.15))
            scan_items: list[object] = []
            if self._sb_kinds.get(target_id) == "array" and len(target) >= 1:
                try:
                    scan_items = list(target[0])
                except TypeError:
                    scan_items = []
            elif self._sb_kinds.get(target_id) == "point_cloud" and len(target) >= 2:
                try:
                    scan_items = list(target[1])
                except TypeError:
                    scan_items = []
            if not scan_items:
                scan_items = [target]
            color_cycle = [BLUE, TEAL, PURPLE, GOLD]
            self._play(
                LaggedStart(
                    *[
                        Indicate(item, color=color_cycle[i % len(color_cycle)], scale_factor=1.035)
                        for i, item in enumerate(scan_items[:8])
                    ],
                    lag_ratio=0.18,
                ),
                max(0.36, run_time * 0.68),
            )
            return

        if action == "merge":
            self._restore_storyboard_opacity(0.10)
            self._ensure_visible(source_id, min(0.20, run_time * 0.14))
            if source is None or target is None:
                self._ensure_visible(target_id, run_time)
                return
            self._camera_reframe_between(source, target, min(0.20, run_time * 0.14))
            self._play(TransformFromCopy(source, target), max(0.40, run_time * 0.58))
            self._sb_visible.add(target_id)
            # If another visible prompt/document is nearby, briefly connect it
            # so the learner sees that context assembly is additive.
            companions = [
                self._sb_objects[oid]
                for oid in self._sb_visible
                if oid not in {source_id, target_id}
                and self._sb_kinds.get(oid) in {"prompt", "document", "file", "resource"}
            ]
            if companions:
                link = Arrow(
                    companions[0].get_center(), target.get_center(), buff=0.72,
                    color=PURPLE, stroke_width=2.0,
                )
                self._play(GrowArrow(link), min(0.20, run_time * 0.16))
                self._play(FadeOut(link), min(0.12, run_time * 0.08))
            return

        if action == "stream":
            self._restore_storyboard_opacity(0.10)
            self._ensure_visible(source_id, min(0.20, run_time * 0.14))
            if target is None:
                return
            if source is not None:
                self._camera_reframe_between(source, target, min(0.20, run_time * 0.14))
            parts = list(target) if hasattr(target, "__iter__") else []
            if target_id not in self._sb_visible and len(parts) >= 2:
                self._play(
                    LaggedStart(
                        *[FadeIn(part, shift=RIGHT * 0.05) for part in parts],
                        lag_ratio=0.17,
                    ),
                    max(0.42, run_time * 0.72),
                )
                self._sb_visible.add(target_id)
            else:
                self._ensure_visible(target_id, min(0.26, run_time * 0.2))
                self._play(Indicate(target, color=GREEN), max(0.32, run_time * 0.55))
            return

        if action in {"transform", "replace"}:
            self._restore_storyboard_opacity(0.10)
            self._ensure_visible(source_id, min(0.20, run_time * 0.14))
            if source is not None and target is not None:
                self._camera_reframe_between(source, target, min(0.20, run_time * 0.14))
                if action == "transform" and getattr(self, "_sb_layout", "") == "analogy_map":
                    self._play(ReplacementTransform(source, target), max(0.36, run_time * 0.70))
                    self._sb_visible.discard(source_id)
                    self._sb_visible.add(target_id)
                elif action == "transform":
                    self._play(TransformFromCopy(source, target), max(0.36, run_time * 0.70))
                    self._sb_visible.add(target_id)
                else:
                    self._play(FadeOut(source), min(0.24, run_time * 0.22))
                    self._sb_visible.discard(source_id)
                    self._play(FadeIn(target), max(0.30, run_time * 0.55))
                    self._sb_visible.add(target_id)
            return

        if action in {"allow", "reject"}:
            self._restore_storyboard_opacity(0.08)
            self._ensure_visible(source_id, min(0.18, run_time * 0.12))
            self._ensure_visible(target_id, min(0.20, run_time * 0.15))
            if destination_id:
                self._ensure_visible(destination_id, min(0.20, run_time * 0.15))
            color = GREEN if action == "allow" else RED
            word = str(beat.get("label") or ("ALLOW" if action == "allow" else "BLOCK"))
            if source is not None and target is not None:
                self._camera_reframe_between(source, destination or target, min(0.18, run_time * 0.12))
                probe = Dot(color=color, radius=0.09).move_to(source.get_center())
                self.add(probe)
                self._play(
                    MoveAlongPath(probe, Line(source.get_center(), target.get_center())),
                    max(0.24, run_time * 0.24),
                )
                if destination is not None:
                    self._play(
                        MoveAlongPath(probe, Line(target.get_center(), destination.get_center())),
                        max(0.24, run_time * 0.24),
                    )
            badge = self._pill(word, color)
            anchor = destination if destination is not None else target
            if anchor is not None:
                badge.next_to(anchor, DOWN, buff=0.16)
            self._play(FadeIn(badge, shift=UP * 0.05), max(0.24, run_time * 0.20))
            self._play(Indicate(badge, color=color), max(0.20, run_time * 0.14))
            return

        if action == "compare":
            self._ensure_visible(source_id, min(0.18, run_time * 0.14))
            self._ensure_visible(destination_id or target_id, min(0.18, run_time * 0.14))
            other = destination if destination is not None else target
            if source is not None and other is not None:
                self._camera_reframe_between(source, other, min(0.20, run_time * 0.14))
            animations = []
            if source is not None:
                animations.append(Indicate(source, color=GREEN))
            if other is not None:
                animations.append(Indicate(other, color=RED))
            if animations:
                self._play(AnimationGroup(*animations, lag_ratio=0.25), max(0.32, run_time * 0.60))
            return

        self._ensure_visible(target_id, run_time)

    # ------------------------------------------------------------------
    # Semantic archetypes
    # ------------------------------------------------------------------
    def _render_many_to_one(self) -> list[object]:
        sources = VGroup(*[self._node(label, PURPLE, 2.1, 0.7) for label in self.labels[:3]])
        sources.arrange(DOWN, buff=0.32).shift(LEFT * 4.0 + DOWN * 0.25)
        hub = self._node(self.labels[3] if len(self.labels) > 3 else "Standard interface", TEAL, 2.5, 1.0).shift(RIGHT * 0.2)
        target = self._node(self.labels[4] if len(self.labels) > 4 else "Reusable clients", GREEN, 2.45, 0.9).shift(RIGHT * 4.0)
        self._play(LaggedStart(*[FadeIn(n, shift=RIGHT * 0.12) for n in sources], lag_ratio=0.18), 0.95)
        arrows = VGroup(*[Arrow(n.get_right(), hub.get_left(), buff=0.08, color=PURPLE, stroke_width=3) for n in sources])
        self._play(AnimationGroup(FadeIn(hub), *[GrowArrow(a) for a in arrows], lag_ratio=0.08), 1.0)
        bridge = Arrow(hub.get_right(), target.get_left(), buff=0.08, color=TEAL, stroke_width=4)
        self._play(AnimationGroup(GrowArrow(bridge), FadeIn(target, shift=LEFT * 0.1)), 0.85)
        packet = Dot(color=GOLD, radius=0.085).move_to(sources[0].get_right())
        self.add(packet)
        self._play(MoveAlongPath(packet, Line(sources[0].get_right(), hub.get_left())), 0.7)
        self._play(MoveAlongPath(packet, Line(hub.get_right(), target.get_left())), 0.7)
        return [*sources, hub, target]

    def _render_architecture_network(self) -> list[object]:
        names = (self.labels + ["Client", "Service", "Data", "Tool"])[:4]
        nodes = [self._node(name, [BLUE, TEAL, PURPLE, GREEN][i]) for i, name in enumerate(names)]
        nodes[0].move_to(LEFT * 4.0 + UP * 1.15)
        nodes[1].move_to(LEFT * 0.9 + UP * 1.15)
        nodes[2].move_to(RIGHT * 2.5 + UP * 1.15)
        nodes[3].move_to(RIGHT * 0.6 + DOWN * 1.45)
        self._play(LaggedStart(*[FadeIn(n, shift=UP * 0.08) for n in nodes], lag_ratio=0.12), 0.9)
        edges = VGroup(
            Arrow(nodes[0].get_right(), nodes[1].get_left(), buff=0.08, color=BLUE),
            Arrow(nodes[1].get_right(), nodes[2].get_left(), buff=0.08, color=TEAL),
            Arrow(nodes[1].get_bottom(), nodes[3].get_top(), buff=0.08, color=PURPLE),
        )
        self._play(LaggedStart(*[GrowArrow(e) for e in edges], lag_ratio=0.16), 0.9)
        packet = Dot(radius=0.09, color=GOLD).move_to(nodes[0].get_right())
        self.add(packet)
        self._play(MoveAlongPath(packet, Line(nodes[0].get_right(), nodes[1].get_left())), 0.75)
        self._play(MoveAlongPath(packet, Line(nodes[1].get_right(), nodes[2].get_left())), 0.75)
        self._play(Indicate(nodes[3], color=PURPLE), 0.55)
        return nodes

    def _render_capability_orbit(self) -> list[object]:
        center = self._node(self.labels[0], TEAL, 2.8, 1.0).move_to(ORIGIN + UP * 0.2)
        self._play(FadeIn(center, scale=0.9), 0.65)
        orbit_labels = (self.labels[1:] + ["Tools", "Resources", "Prompts"])[:3]
        positions = [LEFT * 3.7 + UP * 1.3, RIGHT * 3.7 + UP * 1.3, DOWN * 2.2]
        satellites = [self._node(name, [PURPLE, BLUE, GREEN][i], 2.15, 0.72).move_to(positions[i]) for i, name in enumerate(orbit_labels)]
        self._play(LaggedStart(*[FadeIn(s, shift=(ORIGIN - s.get_center()) * 0.08) for s in satellites], lag_ratio=0.2), 0.9)
        curves = VGroup(*[CurvedArrow(center.get_center(), s.get_center(), angle=0.22, color=[PURPLE, BLUE, GREEN][i]) for i, s in enumerate(satellites)])
        self._play(LaggedStart(*[Create(c) for c in curves], lag_ratio=0.18), 0.9)
        for sat in satellites:
            self._play(Indicate(sat, color=GOLD), 0.45)
        return [center, *satellites]

    def _render_message_exchange(self) -> list[object]:
        left = self._node(self.labels[0], BLUE, 2.6, 1.05).shift(LEFT * 4.0)
        right = self._node(self.labels[1] if len(self.labels) > 1 else "Server", TEAL, 2.6, 1.05).shift(RIGHT * 4.0)
        self._play(AnimationGroup(FadeIn(left, shift=RIGHT * 0.12), FadeIn(right, shift=LEFT * 0.12)), 0.8)
        req_path = Line(left.get_right(), right.get_left())
        req = self._pill(self.labels[2] if len(self.labels) > 2 else "request", GOLD).move_to(left.get_right() + RIGHT * 0.7 + UP * 0.45)
        self._play(FadeIn(req), 0.4)
        self._play(MoveAlongPath(req, req_path.copy().shift(UP * 0.45)), 1.0)
        self._play(Indicate(right, color=TEAL), 0.55)
        resp = self._pill(self.labels[3] if len(self.labels) > 3 else "response", GREEN).move_to(right.get_left() + LEFT * 0.7 + DOWN * 0.55)
        self._play(FadeIn(resp), 0.35)
        self._play(MoveAlongPath(resp, Line(right.get_left() + DOWN * 0.55, left.get_right() + DOWN * 0.55)), 1.0)
        return [left, right, req, resp]

    def _render_request_response(self) -> list[object]:
        return self._render_message_exchange()

    def _render_validation_gate(self) -> list[object]:
        input_box = self._node(self.labels[0], BLUE, 2.5, 0.9).shift(LEFT * 4.2)
        gate = VGroup(
            RoundedRectangle(width=2.4, height=2.0, corner_radius=0.16, fill_color=PANEL, fill_opacity=1, stroke_color=GOLD, stroke_width=3),
            self._label(self.labels[1] if len(self.labels) > 1 else "Validation", 22, GOLD),
        )
        gate[1].move_to(gate[0])
        gate.move_to(ORIGIN)
        good = self._node(self.labels[2] if len(self.labels) > 2 else "Valid", GREEN, 2.25, 0.82).shift(RIGHT * 4.0 + UP * 1.0)
        bad = self._node(self.labels[3] if len(self.labels) > 3 else "Rejected", RED, 2.25, 0.82).shift(RIGHT * 4.0 + DOWN * 1.3)
        self._play(FadeIn(input_box), 0.55)
        self._play(FadeIn(gate, scale=0.92), 0.6)
        probe = Dot(color=BLUE, radius=0.09).move_to(input_box.get_right())
        self.add(probe)
        self._play(MoveAlongPath(probe, Line(input_box.get_right(), gate.get_left())), 0.7)
        self._play(Indicate(gate, color=GOLD), 0.65)
        self._play(AnimationGroup(FadeIn(good, shift=LEFT * 0.1), FadeIn(bad, shift=LEFT * 0.1)), 0.65)
        self._play(MoveAlongPath(probe, Line(gate.get_right(), good.get_left())), 0.65)
        self._play(Indicate(bad, color=RED), 0.45)
        return [input_box, gate, good, bad]

    def _render_security_boundary(self) -> list[object]:
        boundary = RoundedRectangle(width=6.4, height=4.1, corner_radius=0.25, stroke_color=RED, stroke_width=3, fill_color="#191623", fill_opacity=0.55).shift(RIGHT * 1.4 + DOWN * 0.15)
        protected = self._node(self.labels[1] if len(self.labels) > 1 else "Protected resource", GREEN, 2.7, 0.9).move_to(boundary.get_center())
        actor = self._node(self.labels[0], BLUE, 2.4, 0.85).shift(LEFT * 4.5)
        check = self._pill(self.labels[2] if len(self.labels) > 2 else "Permission check", GOLD).move_to(LEFT * 0.8 + UP * 1.7)
        self._play(FadeIn(actor), 0.45)
        self._play(Create(boundary), 0.75)
        self._play(FadeIn(protected), 0.55)
        attempt = Arrow(actor.get_right(), boundary.get_left(), buff=0.08, color=RED, stroke_width=3)
        self._play(GrowArrow(attempt), 0.75)
        self._play(FadeIn(check, shift=DOWN * 0.08), 0.5)
        self._play(Indicate(check, color=GOLD), 0.55)
        self._play(Indicate(protected, color=GREEN), 0.55)
        return [actor, boundary, protected, check]

    def _render_tradeoff_balance(self) -> list[object]:
        left = self._node(self.labels[0], GREEN, 3.4, 1.0).shift(LEFT * 3.3 + UP * 0.5)
        right = self._node(self.labels[1] if len(self.labels) > 1 else "Responsibility", RED, 3.4, 1.0).shift(RIGHT * 3.3 + UP * 0.5)
        beam = Line(LEFT * 3.0, RIGHT * 3.0, color=GOLD, stroke_width=5).shift(DOWN * 1.05)
        pivot = Triangle(color=GOLD, fill_color=GOLD, fill_opacity=1).scale(0.35).rotate(3.14159).shift(DOWN * 1.65)
        self._play(AnimationGroup(FadeIn(left, shift=RIGHT * 0.1), FadeIn(right, shift=LEFT * 0.1)), 0.75)
        self._play(AnimationGroup(Create(beam), FadeIn(pivot)), 0.7)
        self._play(Indicate(left, color=GREEN), 0.55)
        self._play(Indicate(right, color=RED), 0.55)
        takeaway = self._pill(self.labels[2] if len(self.labels) > 2 else "Design deliberately", TEAL).shift(DOWN * 2.55)
        self._play(FadeIn(takeaway, shift=UP * 0.1), 0.55)
        return [left, right, takeaway]

    def _render_retrieval_pipeline(self) -> list[object]:
        docs = VGroup(*[Rectangle(width=0.9, height=1.15, color=BLUE, fill_color=PANEL_2, fill_opacity=1) for _ in range(3)])
        docs.arrange(RIGHT, buff=0.22).shift(LEFT * 4.5 + UP * 0.8)
        index = self._node(self.labels[1] if len(self.labels) > 1 else "Vector index", PURPLE, 2.4, 0.9).shift(LEFT * 1.2 + UP * 0.8)
        context = self._node(self.labels[2] if len(self.labels) > 2 else "Retrieved context", TEAL, 2.7, 0.9).shift(RIGHT * 2.1 + UP * 0.8)
        answer = self._node(self.labels[3] if len(self.labels) > 3 else "Grounded answer", GREEN, 2.4, 0.9).shift(RIGHT * 4.6 + DOWN * 1.5)
        self._play(LaggedStart(*[FadeIn(d, shift=UP * 0.1) for d in docs], lag_ratio=0.15), 0.7)
        self._play(AnimationGroup(FadeIn(index), GrowArrow(Arrow(docs.get_right(), index.get_left(), buff=0.08, color=BLUE))), 0.8)
        self._play(AnimationGroup(FadeIn(context), GrowArrow(Arrow(index.get_right(), context.get_left(), buff=0.08, color=PURPLE))), 0.8)
        self._play(AnimationGroup(FadeIn(answer), GrowArrow(CurvedArrow(context.get_bottom(), answer.get_left(), angle=-0.35, color=TEAL))), 0.85)
        return [docs, index, context, answer]

    def _render_browser_action(self) -> list[object]:
        """Render a browser interaction with conservative Manim primitives.

        Keep this path intentionally simple for Cairo compatibility: no nested
        path animation is required for correctness, and the visible state
        change is the teaching signal.
        """
        browser = RoundedRectangle(
            width=7.4, height=4.25, corner_radius=0.18,
            fill_color=PANEL, fill_opacity=1, stroke_color=BLUE, stroke_width=2.4,
        ).shift(LEFT * 0.45 + DOWN * 0.15)
        bar = Rectangle(
            width=7.05, height=0.46, fill_color="#1E293B",
            fill_opacity=1, stroke_width=0,
        ).move_to(browser.get_top() + DOWN * 0.36)
        target = RoundedRectangle(
            width=2.45, height=0.72, corner_radius=0.12,
            fill_color="#12352F", fill_opacity=1,
            stroke_color=TEAL, stroke_width=2,
        ).move_to(browser.get_center() + RIGHT * 1.25)
        label = self._label(self.labels[1] if len(self.labels) > 1 else "Target element", 18).move_to(target)
        target_group = VGroup(target, label)
        cursor = Dot(color=GOLD, radius=0.11).move_to(LEFT * 4.2 + DOWN * 1.75)

        self._play(FadeIn(browser), 0.5)
        self._play(FadeIn(bar), 0.3)
        self._play(FadeIn(target_group), 0.45)
        self._play(FadeIn(cursor), 0.25)
        self._play(cursor.animate.move_to(target.get_center() + LEFT * 0.15), 0.8)
        self._play(Indicate(target_group, color=TEAL), 0.55)

        state = self._pill(
            self.labels[2] if len(self.labels) > 2 else "State changed", GREEN
        ).shift(LEFT * 2.9 + DOWN * 2.25)
        self._play(FadeIn(state, shift=UP * 0.08), 0.4)
        return [browser, target_group, cursor, state]

    def _render_browser_test(self) -> list[object]:
        focus = self._render_browser_action()
        assertion = self._pill(
            self.labels[3] if len(self.labels) > 3 else "Expected state", PURPLE
        ).shift(RIGHT * 3.55 + DOWN * 1.95)
        result = self._pill("PASS", GREEN).shift(RIGHT * 3.55 + DOWN * 2.65)
        self._play(FadeIn(assertion, shift=LEFT * 0.1), 0.4)
        self._play(Indicate(assertion, color=PURPLE), 0.45)
        self._play(FadeIn(result, shift=UP * 0.08), 0.35)
        return [*focus, assertion, result]

    def _render_query_table(self) -> list[object]:
        table = VGroup()
        for r in range(4):
            for c in range(4):
                cell = Rectangle(width=1.35, height=0.62, stroke_color="#64748B", stroke_width=1.5, fill_color=PANEL, fill_opacity=1)
                cell.shift(RIGHT * (c - 1.5) * 1.35 + DOWN * (r - 1.5) * 0.62 + RIGHT * 1.5)
                table.add(cell)
        query = self._pill(self.labels[0], GOLD).shift(LEFT * 4.5 + UP * 1.0)
        self._play(Create(table), 0.9)
        self._play(FadeIn(query), 0.45)
        self._play(MoveAlongPath(query, Line(query.get_center(), table.get_left() + LEFT * 0.15)), 0.9)
        row = VGroup(*table[8:12])
        self._play(Indicate(row, color=TEAL), 0.65)
        result = self._pill(self.labels[2] if len(self.labels) > 2 else "Result", GREEN).shift(LEFT * 3.8 + DOWN * 1.5)
        self._play(FadeIn(result), 0.45)
        return [table, query, result]

    def _render_algorithm_trace(self) -> list[object]:
        values = [label[:8] for label in self.labels[:5]]
        cells = VGroup(*[self._node(value, BLUE, 1.75, 0.85) for value in values]).arrange(RIGHT, buff=0.18).move_to(UP * 0.45)
        self._play(LaggedStart(*[FadeIn(c, shift=UP * 0.08) for c in cells], lag_ratio=0.1), 0.8)
        pointer = Triangle(color=GOLD, fill_color=GOLD, fill_opacity=1).scale(0.13).rotate(3.14159).next_to(cells[0], UP, buff=0.08)
        self._play(FadeIn(pointer), 0.35)
        if len(cells) > 2:
            self._play(pointer.animate.next_to(cells[len(cells)//2], UP, buff=0.08), 0.8)
        if len(cells) > 3:
            self._play(pointer.animate.next_to(cells[-1], UP, buff=0.08), 0.8)
        self._play(Indicate(cells[-1], color=GREEN), 0.55)
        return [*cells, pointer]

    def _render_agent_tool_loop(self) -> list[object]:
        agent = Circle(radius=1.0, color=TEAL, fill_color="#12352F", fill_opacity=1).shift(LEFT * 2.0)
        agent_label = self._label(self.labels[0], 20).move_to(agent)
        tool = self._node(self.labels[1] if len(self.labels) > 1 else "Tool", PURPLE, 2.4, 0.9).shift(RIGHT * 3.0 + UP * 1.3)
        obs = self._node(self.labels[2] if len(self.labels) > 2 else "Observation", BLUE, 2.4, 0.9).shift(RIGHT * 3.0 + DOWN * 1.4)
        agent_group = VGroup(agent, agent_label)
        self._play(FadeIn(agent_group, scale=0.9), 0.55)
        self._play(AnimationGroup(FadeIn(tool), FadeIn(obs)), 0.65)
        to_tool = CurvedArrow(agent.get_right(), tool.get_left(), angle=0.25, color=PURPLE)
        to_obs = Arrow(tool.get_bottom(), obs.get_top(), buff=0.08, color=BLUE)
        back = CurvedArrow(obs.get_left(), agent.get_bottom(), angle=-0.28, color=TEAL)
        self._play(LaggedStart(GrowArrow(to_tool), GrowArrow(to_obs), GrowArrow(back), lag_ratio=0.22), 1.1)
        dot = Dot(color=GOLD, radius=0.08).move_to(agent.get_right())
        self.add(dot)
        self._play(MoveAlongPath(dot, to_tool.copy()), 0.65)
        self._play(MoveAlongPath(dot, to_obs.copy()), 0.65)
        self._play(MoveAlongPath(dot, back.copy()), 0.65)
        return [agent_group, tool, obs]

    def _render_analogy_transform(self) -> list[object]:
        real = self._node(self.labels[0], GOLD, 3.1, 1.0).shift(LEFT * 3.5)
        tech = self._node(self.labels[1] if len(self.labels) > 1 else "Technical model", TEAL, 3.1, 1.0).shift(RIGHT * 3.5)
        equals = Text("≈", font_size=68, color=PURPLE).move_to(ORIGIN)
        self._play(FadeIn(real, shift=RIGHT * 0.1), 0.6)
        self._play(Write(equals), 0.5)
        self._play(FadeIn(tech, shift=LEFT * 0.1), 0.6)
        mapping = VGroup(*[self._pill(label, [BLUE, PURPLE, GREEN][i % 3]) for i, label in enumerate(self.labels[2:5])]).arrange(DOWN, buff=0.25).shift(DOWN * 2.0)
        if len(mapping):
            self._play(LaggedStart(*[FadeIn(m, shift=UP * 0.08) for m in mapping], lag_ratio=0.16), 0.85)
        return [real, tech, *mapping]

    def _render_timeline_build(self) -> list[object]:
        line = Line(LEFT * 5.0, RIGHT * 5.0, color="#64748B", stroke_width=4).shift(DOWN * 0.3)
        self._play(Create(line), 0.7)
        names = self.labels[:4]
        dots = []
        for i, name in enumerate(names):
            x = -4.5 + i * (9.0 / max(1, len(names) - 1))
            dot = Dot([x, -0.3, 0], color=[BLUE, PURPLE, TEAL, GREEN][i % 4], radius=0.11)
            label = self._label(name, 18).next_to(dot, UP if i % 2 == 0 else DOWN, buff=0.22)
            group = VGroup(dot, label)
            dots.append(group)
            self._play(FadeIn(group, scale=0.85), 0.45)
        marker = Dot(color=GOLD, radius=0.08).move_to(line.get_start())
        self.add(marker)
        self._play(MoveAlongPath(marker, line), 1.2)
        return dots

    def _render_code_execution(self) -> list[object]:
        panel = RoundedRectangle(width=8.4, height=4.7, corner_radius=0.18, fill_color="#0B1220", fill_opacity=1, stroke_color="#52677F", stroke_width=2).shift(LEFT * 0.7 + DOWN * 0.2)
        self._play(FadeIn(panel), 0.45)
        rows = VGroup()
        snippets = self.labels[:5]
        for i, text in enumerate(snippets, start=1):
            line = self._code_text(f"{i:>2}  {text}", 20, TEXT)
            rows.add(line)
        rows.arrange(DOWN, aligned_edge=LEFT, buff=0.23).move_to(panel.get_center() + LEFT * 0.35)
        self._play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.08) for r in rows], lag_ratio=0.12), 0.9)
        focusables = [panel]
        for row in rows:
            highlight = SurroundingRectangle(row, color=GOLD, buff=0.08, stroke_width=2)
            self._play(Create(highlight), 0.28)
            self._play(FadeOut(highlight), 0.22)
            focusables.append(row)
        return focusables

    def _render_concept_map(self) -> list[object]:
        core = self._node(self.labels[0], TEAL, 2.8, 0.95).move_to(ORIGIN)
        self._play(FadeIn(core, scale=0.9), 0.55)
        positions = [LEFT * 4 + UP * 1.6, RIGHT * 4 + UP * 1.6, LEFT * 3.4 + DOWN * 1.8, RIGHT * 3.4 + DOWN * 1.8]
        others = [self._node(name, [PURPLE, BLUE, GOLD, GREEN][i], 2.3, 0.75).move_to(positions[i]) for i, name in enumerate(self.labels[1:5])]
        self._play(LaggedStart(*[FadeIn(n) for n in others], lag_ratio=0.16), 0.8)
        arrows = [Arrow(n.get_center(), core.get_center(), buff=1.25, color=[PURPLE, BLUE, GOLD, GREEN][i], stroke_width=2.5) for i, n in enumerate(others)]
        if arrows:
            self._play(LaggedStart(*[GrowArrow(a) for a in arrows], lag_ratio=0.14), 0.9)
        return [core, *others]

    def _render_build_challenge(self) -> list[object]:
        goal = self._node(self.labels[0], TEAL, 3.0, 0.9).shift(UP * 2.0)
        self._play(FadeIn(goal), 0.5)
        parts = VGroup(*[self._node(name, [BLUE, PURPLE, GOLD][i % 3], 2.1, 0.7) for i, name in enumerate(self.labels[1:4])]).arrange(RIGHT, buff=0.35).shift(DOWN * 0.6)
        self._play(LaggedStart(*[FadeIn(p, shift=UP * 0.1) for p in parts], lag_ratio=0.15), 0.75)
        arrows = [Arrow(p.get_top(), goal.get_bottom(), buff=0.12, color=TEAL, stroke_width=2.5) for p in parts]
        if arrows:
            self._play(LaggedStart(*[GrowArrow(a) for a in arrows], lag_ratio=0.12), 0.8)
        check = self._pill(self.labels[4] if len(self.labels) > 4 else "Verify the build", GREEN).shift(DOWN * 2.4)
        self._play(FadeIn(check), 0.5)
        return [goal, *parts, check]

    def _render_concept_reveal(self) -> list[object]:
        question = self._pill(self.labels[0], GOLD).shift(UP * 2.1)
        self._play(FadeIn(question, shift=DOWN * 0.1), 0.5)
        cards = VGroup(*[self._node(name, [BLUE, PURPLE, TEAL, GREEN][i % 4], 2.5, 0.8) for i, name in enumerate(self.labels[1:5])])
        if len(cards):
            cards.arrange_in_grid(rows=2, cols=2, buff=(0.55, 0.55)).shift(DOWN * 0.45)
            self._play(LaggedStart(*[FadeIn(c, shift=UP * 0.08) for c in cards], lag_ratio=0.15), 0.9)
        return [question, *cards]
