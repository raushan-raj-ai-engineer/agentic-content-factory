from pathlib import Path

from content_factory.thumbnail.base import ThumbnailGenerator
from content_factory.visual.local import LocalVisualProvider


class LocalThumbnailGenerator(ThumbnailGenerator):
    """Generate thumbnails locally using the existing local visual provider."""

    def __init__(self) -> None:
        self._visual_provider = LocalVisualProvider()

    async def generate(
        self,
        prompt: str,
        output_path: str,
    ) -> None:
        if not prompt.strip():
            raise ValueError("Thumbnail prompt cannot be empty.")

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        enhanced_prompt = (
            "Professional YouTube thumbnail composition. "
            "Strong visual hierarchy, high contrast, clear focal subject, "
            "minimal clutter, no unreadable text. "
            f"Concept: {prompt}"
        )

        await self._visual_provider.generate(
            prompt=enhanced_prompt,
            output_path=str(path),
            title="YouTube Thumbnail",
            description=enhanced_prompt,
            visual_type="concept",
        )

        if not path.is_file():
            raise RuntimeError(
                f"Thumbnail was not created: {path}"
            )
