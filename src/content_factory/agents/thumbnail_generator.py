from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from PIL import (
    Image,
    ImageDraw,
    ImageEnhance,
    ImageFilter,
    ImageFont,
    ImageOps,
)

from content_factory.agents.base import Agent
from content_factory.models.content import (
    ThumbnailArtifact,
    ThumbnailGenerationResult,
)
from content_factory.orchestration.state import WorkflowState
from content_factory.thumbnail.base import ThumbnailGenerator
from content_factory.utils.artifact_paths import artifact_subdir


class ThumbnailGenerationAgent(Agent):
    """
    Use the video's strongest opening visual as the thumbnail base.

    Benefits:
    - thumbnail and first seconds visually match
    - no separate low-quality AI thumbnail generation
    - no AI-generated gibberish typography
    - A/B/C text/layout stays sharp and deterministic
    """

    WIDTH = 1280
    HEIGHT = 720

    def __init__(
        self,
        thumbnail_generator: ThumbnailGenerator,
        output_root: str = "artifacts",
    ) -> None:
        # Keep constructor compatibility; provider is no longer needed for
        # background generation because we reuse generated scene artwork.
        self._thumbnail_generator = thumbnail_generator
        self._output_root = Path(
            output_root
        )

    @property
    def name(
        self,
    ) -> str:
        return "Thumbnail Generation Agent"

    async def execute(
        self,
        state: WorkflowState,
    ) -> WorkflowState:
        if (
            state.production_plan is None
            or state.visual_generation is None
        ):
            raise ValueError(
                "Production plan and generated visuals are required."
            )

        if not state.visual_generation.artifacts:
            raise ValueError(
                "At least one generated visual is required."
            )

        output_dir = artifact_subdir(
            state,
            "thumbnail",
            self._output_root,
        )

        packaging = state.metadata.get(
            "packaging",
            {},
        )

        variants = list(
            packaging.get(
                "variants",
                [],
            )
        )[:3]

        if not variants:
            variants = [
                {
                    "label": "A",
                    "title": state.production_plan.title,
                    "thumbnail_text": "",
                    "angle": "default",
                    "promise_alignment": "opening visual",
                }
            ]

        source = self._pick_opening_visual(
            state
        )

        base_path = (
            output_dir
            / "thumbnail_base.png"
        )

        self._prepare_base(
            source,
            base_path,
        )

        generated = []

        for index, variant in enumerate(
            variants
        ):
            letter = chr(
                ord(
                    "A"
                )
                + index
            )

            target = (
                output_dir
                / f"thumbnail_{letter}.png"
            )

            self._compose(
                base_path=base_path,
                output_path=target,
                variant=variant,
                index=index,
            )

            generated.append(
                {
                    **variant,
                    "letter": letter,
                    "file_path": str(
                        target
                    ),
                }
            )

            print(
                f"[THUMBNAIL] Variant {letter}: {target}"
            )

        default_index = max(
            0,
            min(
                int(
                    packaging.get(
                        "default_index",
                        0,
                    )
                ),
                len(
                    generated
                )
                - 1,
            ),
        )

        final_path = (
            output_dir
            / "thumbnail.png"
        )

        shutil.copy2(
            generated[
                default_index
            ][
                "file_path"
            ],
            final_path,
        )

        manifest = (
            output_dir
            / "thumbnail_variants.json"
        )

        manifest.write_text(
            json.dumps(
                {
                    "source_opening_visual": str(
                        source
                    ),
                    "default_index": default_index,
                    "default_file": str(
                        final_path
                    ),
                    "variants": generated,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        state.thumbnail_generation = (
            ThumbnailGenerationResult(
                artifact=ThumbnailArtifact(
                    file_path=str(
                        final_path
                    ),
                    provider="local-opening-visual",
                    status="generated",
                )
            )
        )

        state.status = (
            "thumbnail_generated"
        )

        print(
            f"[THUMBNAIL] Opening-scene continuity: {source.name}"
        )
        print(
            f"[ARTIFACT] Thumbnail default: {final_path}"
        )

        return state

    @staticmethod
    def _pick_opening_visual(
        state: WorkflowState,
    ) -> Path:
        artifacts = list(
            state.visual_generation.artifacts
        )

        # Prefer first or second visual because they are intentionally premium
        # opening frames in the production plan.
        for artifact in artifacts[
            :2
        ]:
            path = Path(
                artifact.file_path
            )

            if path.is_file():
                return path

        path = Path(
            artifacts[
                0
            ].file_path
        )

        if not path.is_file():
            raise FileNotFoundError(
                f"Opening visual missing: {path}"
            )

        return path

    @classmethod
    def _prepare_base(
        cls,
        source: Path,
        target: Path,
    ) -> None:
        with Image.open(
            source
        ) as image:
            image = image.convert(
                "RGB"
            )

            image = ImageOps.fit(
                image,
                (
                    cls.WIDTH,
                    cls.HEIGHT,
                ),
                method=Image.Resampling.LANCZOS,
                centering=(
                    0.5,
                    0.48,
                ),
            )

            image = ImageEnhance.Contrast(
                image
            ).enhance(
                1.08
            )

            image = image.filter(
                ImageFilter.UnsharpMask(
                    radius=0.8,
                    percent=105,
                    threshold=3,
                )
            )

            image.save(
                target,
                format="PNG",
                optimize=True,
            )

    @classmethod
    def _compose(
        cls,
        *,
        base_path: Path,
        output_path: Path,
        variant: dict[str, Any],
        index: int,
    ) -> None:
        with Image.open(
            base_path
        ) as base:
            image = base.convert(
                "RGBA"
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
        overlay_draw = ImageDraw.Draw(
            overlay
        )

        # Gradient for readability while keeping the artwork dominant.
        if index == 0:
            for y in range(
                cls.HEIGHT
            ):
                alpha = int(
                    max(
                        0.0,
                        (
                            y
                            / cls.HEIGHT
                            - 0.46
                        )
                        / 0.54,
                    )
                    * 225
                )
                if alpha:
                    overlay_draw.line(
                        (
                            0,
                            y,
                            cls.WIDTH,
                            y,
                        ),
                        fill=(
                            5,
                            7,
                            12,
                            alpha,
                        ),
                    )
        else:
            side_left = (
                index == 1
            )

            for x in range(
                cls.WIDTH
            ):
                fraction = (
                    1
                    - x
                    / cls.WIDTH
                    if side_left
                    else x
                    / cls.WIDTH
                )

                alpha = int(
                    max(
                        0.0,
                        fraction
                        - 0.35,
                    )
                    / 0.65
                    * 220
                )

                if alpha:
                    overlay_draw.line(
                        (
                            x,
                            0,
                            x,
                            cls.HEIGHT,
                        ),
                        fill=(
                            5,
                            7,
                            12,
                            alpha,
                        ),
                    )

        image = Image.alpha_composite(
            image,
            overlay,
        )

        draw = ImageDraw.Draw(
            image
        )

        text = str(
            variant.get(
                "thumbnail_text",
                ""
            )
            or ""
        ).strip()

        if not text:
            text = cls._fallback_text(
                str(
                    variant.get(
                        "title",
                        "",
                    )
                )
            )

        text = " ".join(
            text.split()[
                :4
            ]
        ).upper()

        if index == 0:
            box = (
                65,
                470,
                1215,
                690,
            )
            max_width = 1080
        elif index == 1:
            box = (
                60,
                75,
                720,
                650,
            )
            max_width = 590
        else:
            box = (
                560,
                75,
                1220,
                650,
            )
            max_width = 590

        font = cls._fit_font(
            draw,
            text,
            max_width=max_width,
            max_size=78,
            min_size=42,
            max_lines=3,
        )

        cls._draw_wrapped(
            draw,
            text,
            (
                box[
                    0
                ]
                + 18,
                box[
                    1
                ]
                + 18,
            ),
            font,
            max_width=max_width,
            max_lines=3,
        )

        image.convert(
            "RGB"
        ).save(
            output_path,
            format="PNG",
            optimize=True,
        )

    @staticmethod
    def _fallback_text(
        title: str,
    ) -> str:
        words = re.findall(
            r"[A-Za-zÀ-ÿ0-9'’-]+",
            title,
        )

        blocked = {
            "the",
            "a",
            "an",
            "why",
            "what",
            "how",
            "is",
            "are",
            "explained",
        }

        chosen = [
            word
            for word in words
            if word.lower()
            not in blocked
        ][
            :4
        ]

        return (
            " ".join(
                chosen
            )
            or "WATCH THIS"
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
                size
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
            min_size
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
    ) -> None:
        x, y = xy

        for line in cls._wrap(
            draw,
            text,
            font,
            max_width,
        )[
            :max_lines
        ]:
            draw.text(
                (
                    x,
                    y,
                ),
                line,
                font=font,
                fill=(
                    252,
                    253,
                    255,
                ),
                stroke_width=3,
                stroke_fill=(
                    0,
                    0,
                    0,
                ),
            )

            box = draw.textbbox(
                (
                    x,
                    y,
                ),
                line,
                font=font,
                stroke_width=3,
            )

            y += (
                box[3]
                - box[1]
                + 7
            )

    @staticmethod
    def _wrap(
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.ImageFont,
        max_width: int,
    ) -> list[str]:
        words = text.split()
        lines = []
        current = []

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
    ) -> ImageFont.ImageFont:
        for candidate in (
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Supplemental/Helvetica Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ):
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
                pass

        return ImageFont.load_default()
