from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont


class StudyLayerBuilder:
    """Create a provider-agnostic layered animation fallback for Study Mode.

    Native renderers can emit their own `.layers.json`; this builder is only
    used when the selected visual backend returns a single flattened image.
    """

    WIDTH = 1920
    HEIGHT = 1080

    @classmethod
    def ensure_layers(
        cls,
        *,
        image_path: Path,
        title: str,
        description: str,
        key_elements: list[str],
        visual_type: str,
    ) -> Path:
        manifest_path = image_path.with_suffix(image_path.suffix + ".layers.json")
        if manifest_path.is_file():
            return manifest_path

        layer_dir = image_path.parent / f"{image_path.stem}_layers"
        if layer_dir.exists():
            shutil.rmtree(layer_dir)
        layer_dir.mkdir(parents=True, exist_ok=True)

        source = Image.open(image_path).convert("RGB")
        source = cls._cover(source, cls.WIDTH, cls.HEIGHT)
        background = source.filter(ImageFilter.GaussianBlur(radius=1.4))
        background = ImageEnhance.Brightness(background).enhance(0.48)
        overlay = Image.new("RGBA", background.size, (4, 10, 20, 78))
        base = Image.alpha_composite(background.convert("RGBA"), overlay).convert("RGB")
        base_path = layer_dir / "base.png"
        base.save(base_path, format="PNG")

        items = cls._concepts(key_elements, description)
        manifest: dict[str, object] = {
            "version": 2,
            "canvas": [cls.WIDTH, cls.HEIGHT],
            "base": base_path.name,
            "layers": [],
            "fallback": True,
            "visual_type": visual_type,
        }
        layers: list[dict[str, object]] = manifest["layers"]  # type: ignore[assignment]

        def save_layer(
            *,
            filename: str,
            image: Image.Image,
            x: int,
            y: int,
            kind: str,
            persist: bool = True,
        ) -> None:
            path = layer_dir / filename
            image.save(path, format="PNG")
            layers.append(
                {
                    "file": path.name,
                    "x": x,
                    "y": y,
                    "kind": kind,
                    "persist": persist,
                }
            )

        title_img = Image.new("RGBA", (1660, 150), (0, 0, 0, 0))
        td = ImageDraw.Draw(title_img)
        td.rounded_rectangle(
            (0, 0, 1659, 149),
            radius=28,
            fill=(11, 23, 40, 235),
            outline=(94, 234, 212, 210),
            width=3,
        )
        td.text((42, 22), "STUDY BEAT", font=cls._font(25), fill=(94, 234, 212, 255))
        fitted = cls._fit_text(td, title, 1540, 52, 34)
        td.text((42, 62), fitted[0], font=fitted[1], fill=(248, 250, 252, 255))
        save_layer(filename="01_title.png", image=title_img, x=130, y=90, kind="title")

        colors = [
            ((23, 36, 58, 242), (94, 234, 212, 255)),
            ((30, 31, 58, 242), (196, 181, 253, 255)),
            ((40, 31, 48, 242), (251, 191, 36, 255)),
            ((21, 42, 43, 242), (110, 231, 183, 255)),
        ]
        y_positions = [310, 480, 650, 820]
        for index, concept in enumerate(items[:4]):
            card = Image.new("RGBA", (1380, 130), (0, 0, 0, 0))
            d = ImageDraw.Draw(card)
            fill, accent = colors[index % len(colors)]
            d.rounded_rectangle((0, 0, 1379, 129), radius=24, fill=fill, outline=(82, 98, 121, 230), width=2)
            d.rounded_rectangle((0, 0, 14, 129), radius=7, fill=accent)
            d.text((42, 22), f"STEP {index + 1}", font=cls._font(23), fill=accent)
            text, font = cls._fit_text(d, concept, 1230, 36, 27)
            d.text((42, 59), text, font=font, fill=(241, 245, 249, 255))
            save_layer(
                filename=f"02_concept_{index + 1}.png",
                image=card,
                x=270 if index % 2 == 0 else 330,
                y=y_positions[index],
                kind="concept",
            )

            focus = Image.new("RGBA", (1400, 150), (0, 0, 0, 0))
            fd = ImageDraw.Draw(focus)
            fd.rounded_rectangle((4, 4, 1395, 145), radius=28, outline=accent, width=7)
            save_layer(
                filename=f"03_focus_{index + 1}.png",
                image=focus,
                x=(260 if index % 2 == 0 else 320),
                y=y_positions[index] - 10,
                kind="focus",
                persist=False,
            )

        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest_path

    @classmethod
    def _concepts(cls, key_elements: list[str], description: str) -> list[str]:
        cleaned: list[str] = []
        stop = {"the", "a", "an", "to", "for", "and", "or", "if", "when", "why", "what", "this", "that"}
        for raw in key_elements:
            text = re.sub(r"\s+", " ", str(raw)).strip(" .,:;-_")
            if not text or text.lower() in stop or len(text) < 3:
                continue
            if text.lower() not in {c.lower() for c in cleaned}:
                cleaned.append(text)
            if len(cleaned) >= 4:
                return cleaned

        sentences = [
            re.sub(r"\s+", " ", part).strip()
            for part in re.split(r"(?<=[.!?])\s+", description)
            if part.strip()
        ]
        for sentence in sentences:
            if len(sentence) > 120:
                sentence = sentence[:117].rstrip() + "…"
            if sentence and sentence.lower() not in {c.lower() for c in cleaned}:
                cleaned.append(sentence)
            if len(cleaned) >= 4:
                break
        return cleaned or ["Understand the idea", "Follow the mechanism", "Verify the result"]

    @classmethod
    def _fit_text(
        cls,
        draw: ImageDraw.ImageDraw,
        text: str,
        max_width: int,
        start_size: int,
        min_size: int,
    ) -> tuple[str, ImageFont.ImageFont]:
        value = re.sub(r"\s+", " ", text).strip()
        size = start_size
        font = cls._font(size)
        while draw.textlength(value, font=font) > max_width and size > min_size:
            size -= 2
            font = cls._font(size)
        while draw.textlength(value, font=font) > max_width and len(value) > 12:
            value = value[:-4] + "…"
        return value, font

    @staticmethod
    def _cover(image: Image.Image, width: int, height: int) -> Image.Image:
        ratio = max(width / image.width, height / image.height)
        resized = image.resize((round(image.width * ratio), round(image.height * ratio)), Image.Resampling.LANCZOS)
        left = max(0, (resized.width - width) // 2)
        top = max(0, (resized.height - height) // 2)
        return resized.crop((left, top, left + width, top + height))

    @staticmethod
    def _font(size: int) -> ImageFont.ImageFont:
        candidates = [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/Library/Fonts/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]
        for candidate in candidates:
            if Path(candidate).exists():
                try:
                    return ImageFont.truetype(candidate, size=size)
                except OSError:
                    continue
        return ImageFont.load_default(size=size)
