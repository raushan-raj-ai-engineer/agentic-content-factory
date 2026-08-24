from __future__ import annotations

import contextlib
import json
import os
import sys
import traceback
from pathlib import Path


def emit(value: dict) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    quantize = int(os.getenv("CONTENT_FACTORY_MFLUX_QUANTIZE", "4"))

    try:
        with contextlib.redirect_stdout(sys.stderr):
            from mflux.models.z_image import ZImageTurbo
            model = ZImageTurbo(quantize=quantize)
    except Exception as exc:
        emit(
            {
                "ready": False,
                "error": f"{exc.__class__.__name__}: {exc}",
            }
        )
        return 1

    emit(
        {
            "ready": True,
            "backend": "mflux",
            "model": "z-image-turbo",
            "quantize": quantize,
        }
    )

    for raw in sys.stdin:
        try:
            request = json.loads(raw)
        except Exception:
            emit({"ok": False, "error": "invalid request JSON"})
            continue

        if request.get("cmd") == "shutdown":
            break

        if request.get("cmd") != "generate":
            emit({"ok": False, "error": "unknown command"})
            continue

        try:
            output_path = Path(request["output_path"])
            output_path.parent.mkdir(parents=True, exist_ok=True)

            with contextlib.redirect_stdout(sys.stderr):
                image = model.generate_image(
                    prompt=str(request["prompt"]),
                    seed=int(request.get("seed", 42)),
                    num_inference_steps=int(request.get("steps", 9)),
                    width=int(request.get("width", 1280)),
                    height=int(request.get("height", 720)),
                )
                image.save(str(output_path))

            emit(
                {
                    "ok": True,
                    "output_path": str(output_path),
                    "backend": "mflux",
                    "model": "z-image-turbo",
                    "quantize": quantize,
                }
            )
        except Exception as exc:
            emit(
                {
                    "ok": False,
                    "error": f"{exc.__class__.__name__}: {exc}",
                    "trace": traceback.format_exc()[-2500:],
                }
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
