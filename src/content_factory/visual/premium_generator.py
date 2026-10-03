from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any


class PremiumCreativeGenerator:
    """Persistent MFLUX worker with robust JSON-line protocol parsing."""

    def __init__(
        self,
        project_root: str | Path | None = None,
    ) -> None:
        self._project_root = (
            Path(project_root)
            if project_root is not None
            else Path(__file__).resolve().parents[3]
        )
        self._python = self._project_root / ".visual-venv" / "bin" / "python"
        self._worker = (
            self._project_root
            / "src"
            / "content_factory"
            / "visual"
            / "mflux_worker.py"
        )
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return self._python.is_file() and self._worker.is_file()

    async def generate(
        self,
        *,
        prompt: str,
        output_path: str,
        seed: int,
        width: int = 1280,
        height: int = 720,
        steps: int = 9,
    ) -> dict[str, Any]:
        if not self.available:
            raise RuntimeError(
                "Premium local visual model is not installed. Run: "
                "bash "
                "scripts/setup_premium_visual_model.sh"
            )

        async with self._lock:
            await self._ensure_worker()

            assert self._process is not None
            assert self._process.stdin is not None

            request = {
                "cmd": "generate",
                "prompt": prompt,
                "output_path": str(Path(output_path).resolve()),
                "seed": int(seed),
                "width": int(width),
                "height": int(height),
                "steps": int(steps),
            }

            self._process.stdin.write(
                (json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8")
            )
            await self._process.stdin.drain()

            response = await self._read_protocol_message(
                expected_keys={"ok"},
                timeout=1200.0,
                phase="generation",
            )

            if not response.get("ok"):
                raise RuntimeError(
                    "Premium visual generation failed: "
                    + str(response.get("error", "unknown error"))
                )

            return response

    async def release(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return

        try:
            if process.returncode is None and process.stdin is not None:
                process.stdin.write(b'{"cmd":"shutdown"}\n')
                await process.stdin.drain()
            await asyncio.wait_for(process.wait(), timeout=20.0)
        except Exception:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except Exception:
                    process.kill()

        print("[RESOURCE] Premium MLX visual worker released.")

    async def _ensure_worker(self) -> None:
        if self._process is not None and self._process.returncode is None:
            return

        quantize = self._recommended_quantize()
        env = os.environ.copy()
        env["CONTENT_FACTORY_MFLUX_QUANTIZE"] = str(quantize)

        self._process = await asyncio.create_subprocess_exec(
            str(self._python),
            "-u",
            str(self._worker),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._project_root),
            env=env,
        )

        ready = await self._read_protocol_message(
            expected_keys={"ready"},
            timeout=900.0,
            phase="startup",
        )

        if not ready.get("ready"):
            raise RuntimeError(
                "Premium MFLUX worker failed to initialize: "
                + str(ready.get("error", "unknown error"))
            )

        print(
            "[VISUAL] Premium creative backend ready: "
            f"Z-Image-Turbo / MLX / q{ready.get('quantize', quantize)}"
        )

    async def _read_protocol_message(
        self,
        *,
        expected_keys: set[str],
        timeout: float,
        phase: str,
    ) -> dict[str, Any]:
        process = self._process
        if process is None or process.stdout is None:
            raise RuntimeError("Premium visual worker is not running.")

        async def read_loop() -> dict[str, Any]:
            skipped = 0
            while True:
                raw = await process.stdout.readline()

                if not raw:
                    raise RuntimeError(
                        f"Premium MFLUX worker exited during {phase}."
                    )

                text = raw.decode("utf-8", errors="replace").strip()
                if not text:
                    continue

                try:
                    value = json.loads(text)
                except json.JSONDecodeError:
                    skipped += 1
                    if skipped <= 3:
                        print(
                            "[VISUAL WORKER] Ignored non-protocol output: "
                            + text[:180]
                        )
                    continue

                if isinstance(value, dict) and expected_keys.intersection(value.keys()):
                    return value

                skipped += 1
                if skipped <= 3:
                    print("[VISUAL WORKER] Ignored unrelated JSON output.")

        try:
            return await asyncio.wait_for(read_loop(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise RuntimeError(
                f"Premium MFLUX worker timed out during {phase}."
            ) from exc

    def _recommended_quantize(self) -> int:
        override = os.getenv("CONTENT_FACTORY_MFLUX_QUANTIZE", "").strip()
        if override in {"3", "4", "5", "6", "8"}:
            return int(override)

        memory = self._system_memory_bytes()
        if memory is None:
            return 4

        gib = memory / (1024 * 1024 * 1024)
        return 8 if gib >= 24 else 4

    @staticmethod
    def _system_memory_bytes() -> int | None:
        try:
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            value = result.stdout.strip()
            if value.isdigit():
                return int(value)
        except Exception:
            pass
        return None
