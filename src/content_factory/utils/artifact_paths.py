from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from content_factory.orchestration.state import WorkflowState


DEFAULT_ARTIFACT_ROOT = Path("artifacts")


def slugify_topic(topic: str | None) -> str:
    """Convert a topic into a filesystem-safe readable slug."""
    value = (topic or "untitled-topic").strip()

    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")

    slug = re.sub(
        r"[^a-zA-Z0-9]+",
        "-",
        ascii_value,
    ).strip("-").lower()

    slug = re.sub(r"-{2,}", "-", slug)

    return slug[:80] or "untitled-topic"


def short_run_id(run_id: str | None) -> str:
    value = (run_id or "run").strip()
    safe = re.sub(r"[^a-zA-Z0-9]+", "", value)
    return (safe[:12] or "run").lower()


def topic_root(
    state: WorkflowState,
    root: str | Path = DEFAULT_ARTIFACT_ROOT,
) -> Path:
    return Path(root) / slugify_topic(state.topic)


def artifact_run_dir(
    state: WorkflowState,
    root: str | Path = DEFAULT_ARTIFACT_ROOT,
) -> Path:
    """
    Return:
      artifacts/<topic-slug>/<run-id>/
    """
    topic_dir = topic_root(state, root)
    run_dir = topic_dir / short_run_id(state.run_id)

    run_dir.mkdir(parents=True, exist_ok=True)

    # Human-friendly pointer to the newest run for this topic.
    (topic_dir / "latest.txt").write_text(
        f"{run_dir.name}\n",
        encoding="utf-8",
    )

    metadata_path = run_dir / "run_info.json"

    if not metadata_path.exists():
        metadata = {
            "run_id": state.run_id,
            "topic": state.topic,
            "topic_slug": topic_dir.name,
            "created_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
        }
        metadata_path.write_text(
            json.dumps(
                metadata,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    return run_dir


def artifact_subdir(
    state: WorkflowState,
    name: str,
    root: str | Path = DEFAULT_ARTIFACT_ROOT,
) -> Path:
    path = artifact_run_dir(state, root) / name
    path.mkdir(parents=True, exist_ok=True)
    return path
