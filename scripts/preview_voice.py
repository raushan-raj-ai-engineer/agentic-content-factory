from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from content_factory.voice.local import LocalVoiceProvider


DEFAULT_TEXT = (
    "Welcome. In this lesson, we'll build the idea step by step, "
    "connect the theory to a practical example, and verify what we learned."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview a local narrator voice")
    parser.add_argument("--locale", default="en-US")
    parser.add_argument(
        "--voice-profile",
        choices=["us-male-warm", "us-female-clear", "auto"],
        default="us-male-warm",
    )
    parser.add_argument("--voice", help="Exact installed Piper key or macOS voice name")
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--output", default="artifacts/voice_preview.wav")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    provider = LocalVoiceProvider(
        language=args.locale,
        voice_profile=args.voice_profile,
        preferred_voice=args.voice,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result = await provider.generate_for_segment(
        text=args.text,
        output_path=str(output),
        segment_index=1,
        total_segments=1,
        audience="beginner technical learners in the United States",
        topic="technical study lesson",
    )
    print(f"[VOICE PREVIEW] {output}")
    print(
        "[VOICE PREVIEW] "
        f"backend={result['backend']}, voice={result['voice']}, "
        f"locale={result['locale']}, rate_wpm={result['rate_wpm']}"
    )


if __name__ == "__main__":
    asyncio.run(main())
