from __future__ import annotations

import json
import os
import platform
import resource
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class AgentPerformance:
    agent: str
    elapsed_seconds: float
    rss_start_mb: float | None
    rss_end_mb: float | None
    rss_delta_mb: float | None
    process_peak_rss_mb: float | None
    status: str
    error: str | None = None


class PerformanceProfiler:
    """Lightweight per-agent runtime + memory profiler."""

    def __init__(self) -> None:
        self._records: list[AgentPerformance] = []
        self._workflow_started = time.perf_counter()
        self._started_at = datetime.now(timezone.utc).isoformat()

    def begin(self) -> tuple[float, float | None]:
        return time.perf_counter(), self.current_rss_mb()

    def end(
        self,
        *,
        agent: str,
        started: tuple[float, float | None],
        status: str,
        error: str | None = None,
    ) -> None:
        start_time, rss_start = started
        rss_end = self.current_rss_mb()

        delta = None
        if rss_start is not None and rss_end is not None:
            delta = rss_end - rss_start

        self._records.append(
            AgentPerformance(
                agent=agent,
                elapsed_seconds=round(
                    time.perf_counter() - start_time,
                    3,
                ),
                rss_start_mb=rss_start,
                rss_end_mb=rss_end,
                rss_delta_mb=(
                    round(delta, 2)
                    if delta is not None
                    else None
                ),
                process_peak_rss_mb=self.peak_rss_mb(),
                status=status,
                error=error,
            )
        )

    def write(self, state: Any) -> Path:
        run_dir = self._run_dir(state)
        perf_dir = run_dir / "performance"
        perf_dir.mkdir(parents=True, exist_ok=True)

        total = round(
            time.perf_counter() - self._workflow_started,
            3,
        )

        ordered = sorted(
            self._records,
            key=lambda item: item.elapsed_seconds,
            reverse=True,
        )

        report = {
            "run_id": getattr(state, "run_id", None),
            "topic": getattr(state, "topic", None),
            "started_at_utc": self._started_at,
            "total_elapsed_seconds": total,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
            "current_rss_mb": self.current_rss_mb(),
            "process_peak_rss_mb": self.peak_rss_mb(),
            "agents": [
                asdict(item)
                for item in self._records
            ],
            "top_bottlenecks": [
                {
                    "agent": item.agent,
                    "seconds": item.elapsed_seconds,
                }
                for item in ordered[:5]
            ],
        }

        path = perf_dir / "performance_report.json"
        path.write_text(
            json.dumps(
                report,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        return path

    def print_summary(self, state: Any) -> None:
        path = self.write(state)
        ordered = sorted(
            self._records,
            key=lambda item: item.elapsed_seconds,
            reverse=True,
        )

        print(
            f"[PERF] Total workflow: "
            f"{time.perf_counter() - self._workflow_started:.1f}s"
        )

        for item in ordered[:3]:
            print(
                f"[PERF] Bottleneck: {item.agent} "
                f"{item.elapsed_seconds:.1f}s"
            )

        peak = self.peak_rss_mb()
        if peak is not None:
            print(
                f"[PERF] Process peak RSS: {peak:.0f} MB"
            )

        print(
            f"[PERF] Report: {path}"
        )

    @staticmethod
    def current_rss_mb() -> float | None:
        # ps reports RSS in KiB on macOS/Linux and gives current resident memory,
        # which is more useful than only ru_maxrss.
        try:
            output = subprocess.check_output(
                [
                    "ps",
                    "-o",
                    "rss=",
                    "-p",
                    str(os.getpid()),
                ],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=2,
            ).strip()

            if output:
                return round(
                    float(output) / 1024.0,
                    2,
                )
        except Exception:
            pass

        return None

    @staticmethod
    def peak_rss_mb() -> float | None:
        try:
            value = float(
                resource.getrusage(
                    resource.RUSAGE_SELF
                ).ru_maxrss
            )

            # macOS returns bytes; Linux returns KiB.
            if sys.platform == "darwin":
                return round(
                    value / 1024.0 / 1024.0,
                    2,
                )

            return round(
                value / 1024.0,
                2,
            )
        except Exception:
            return None

    @staticmethod
    def _run_dir(state: Any) -> Path:
        try:
            from content_factory.utils.artifact_paths import artifact_run_dir

            return artifact_run_dir(state)
        except Exception:
            run_id = str(
                getattr(state, "run_id", "run")
                or "run"
            )
            topic = str(
                getattr(state, "topic", "untitled-topic")
                or "untitled-topic"
            )
            safe_topic = re_slug(topic)
            safe_run = "".join(
                ch
                for ch in run_id
                if ch.isalnum()
            )[:12] or "run"

            path = (
                Path("artifacts")
                / safe_topic
                / safe_run
            )
            path.mkdir(
                parents=True,
                exist_ok=True,
            )
            return path


def re_slug(value: str) -> str:
    import re

    slug = re.sub(
        r"[^a-zA-Z0-9]+",
        "-",
        value,
    ).strip("-").lower()

    return slug[:80] or "untitled-topic"
