import argparse
import json
from pathlib import Path

from .catalog import CODES


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Free local DSA lessons and recorded browser demos"
    )
    parser.add_argument("--project", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("list")

    dsa = sub.add_parser("dsa")
    dsa.add_argument("--topic", required=True)
    dsa.add_argument("--values", help='JSON array, e.g. "[0,1,0,3,12]"')
    dsa.add_argument("--target", type=int)
    dsa.add_argument("--text")
    dsa.add_argument("--renderer", choices=["manim", "cards"], default="manim")
    dsa.add_argument("--voice", default="en_US-ryan-medium")
    dsa.add_argument(
        "--llm-provider",
        choices=["auto", "ollama", "gemini", "openai", "anthropic", "compatible"],
        default="auto",
        help=(
            "Optional narration-enhancement provider. One provider/model is locked "
            "for every scene. Default: auto from .env."
        ),
    )
    dsa.add_argument("--llm-model", help="Model override for the locked provider.")
    dsa.add_argument(
        "--no-llm",
        action="store_true",
        help="Use deterministic narration only.",
    )
    # Backward-compatible flags from v0.3.4.
    dsa.add_argument("--ollama", default=None, help=argparse.SUPPRESS)
    dsa.add_argument("--no-ollama", action="store_true", help=argparse.SUPPRESS)
    dsa.add_argument(
        "--preview-scenes",
        type=int,
        help="Generate only the first N scenes, labelled preview",
    )

    demo = sub.add_parser("demo")
    demo.add_argument("--config", type=Path, required=True)
    demo.add_argument("--voice", default="en_US-ryan-medium")
    demo.add_argument("--headed", action="store_true")

    args = parser.parse_args()
    try:
        if args.mode == "list":
            print("\n".join(CODES))
            return

        if args.mode == "dsa":
            from .production import produce_dsa

            if args.preview_scenes is not None and args.preview_scenes < 1:
                parser.error("--preview-scenes must be positive")
            values = json.loads(args.values) if args.values is not None else None
            if values is not None and not isinstance(values, list):
                parser.error("--values must be a JSON array")

            provider = args.llm_provider
            model = args.llm_model
            if args.no_llm or args.no_ollama:
                provider = None
            elif args.ollama is not None:
                provider = "ollama"
                model = args.ollama

            produce_dsa(
                args.project.resolve(),
                args.topic,
                values,
                args.target,
                args.text,
                args.renderer,
                args.voice,
                provider,
                model,
                args.preview_scenes,
            )
            return

        from .browser_demo import produce_demo

        produce_demo(
            args.project.resolve(),
            args.config.resolve(),
            args.voice,
            args.headed,
        )
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
