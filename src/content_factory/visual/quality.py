from __future__ import annotations

from pathlib import Path

from PIL import (
    Image,
    ImageFilter,
    ImageOps,
    ImageStat,
)


TARGET_SIZE = (
    1920,
    1080,
)


def sharpness_score(
    image_path: str | Path,
) -> float:
    path = Path(
        image_path
    )

    with Image.open(
        path
    ) as image:
        gray = ImageOps.grayscale(
            image
        )

        margin_x = max(
            1,
            gray.width // 20,
        )
        margin_y = max(
            1,
            gray.height // 20,
        )

        if (
            gray.width
            > margin_x * 2
            and gray.height
            > margin_y * 2
        ):
            gray = gray.crop(
                (
                    margin_x,
                    margin_y,
                    gray.width - margin_x,
                    gray.height - margin_y,
                )
            )

        edges = gray.filter(
            ImageFilter.FIND_EDGES
        )

        return float(
            ImageStat.Stat(
                edges
            ).var[0]
        )


def dimensions_ok(
    image_path: str | Path,
    *,
    min_width: int = 1280,
    min_height: int = 720,
) -> bool:
    with Image.open(
        image_path
    ) as image:
        return (
            image.width
            >= min_width
            and image.height
            >= min_height
        )


def prepare_for_video(
    image_path: str | Path,
    *,
    target_size: tuple[
        int,
        int,
    ] = TARGET_SIZE,
) -> None:
    path = Path(
        image_path
    )

    with Image.open(
        path
    ) as image:
        image = image.convert(
            "RGB"
        )

        image = ImageOps.fit(
            image,
            target_size,
            method=Image.Resampling.LANCZOS,
            centering=(
                0.5,
                0.5,
            ),
        )

        image = image.filter(
            ImageFilter.UnsharpMask(
                radius=1.0,
                percent=105,
                threshold=3,
            )
        )

        image.save(
            path,
            format="PNG",
            optimize=True,
        )
