from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from typing import Any

from content_factory.orchestration.state import WorkflowState
from content_factory.utils.artifact_paths import artifact_run_dir


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def workflow_result_payload(state: WorkflowState) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for item in fields(state):
        payload[item.name] = _jsonable(getattr(state, item.name))
    return payload


def write_workflow_result(
    state: WorkflowState,
    *,
    root: str | Path = "artifacts",
) -> Path:
    output = artifact_run_dir(state, root) / "workflow_result.json"
    output.write_text(
        json.dumps(
            workflow_result_payload(state),
            indent=2,
            ensure_ascii=False,
            default=str,
        ) + "\n",
        encoding="utf-8",
    )
    return output


def _duration_label(seconds: float | int | None) -> str:
    if not seconds:
        return ""
    total = max(0, int(round(float(seconds))))
    minutes, secs = divmod(total, 60)
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def print_compact_result(
    state: WorkflowState,
    *,
    result_path: str | Path | None = None,
) -> None:
    print()
    print("=" * 60)
    print("WORKFLOW RESULT")
    print("=" * 60)
    print(f"Run ID: {state.run_id}")
    print(f"Topic: {state.topic}")
    print(f"Status: {state.status}")

    provider = str(state.metadata.get("llm_provider") or "").strip()
    model = str(state.metadata.get("llm_model") or "").strip()
    if provider or model:
        print(f"LLM: {provider or 'unknown'} / {model or 'unknown'}")

    mode = str(state.metadata.get("content_mode") or "").strip()
    if mode:
        print(f"Mode: {mode}")

    print(
        "Approvals: "
        f"strategy={'Y' if state.strategy_approved else 'N'}, "
        f"script={'Y' if state.script_approved else 'N'}, "
        f"production={'Y' if state.production_approved else 'N'}"
    )

    failed_agent = state.metadata.get("failed_agent")
    if failed_agent:
        print(f"Failed Agent: {failed_agent}")
        error = str(state.metadata.get("error") or "").strip()
        if error:
            print(f"Error: {error}")

    if state.script is not None:
        script_length = state.metadata.get("script_length", {})
        words = script_length.get("words")
        duration = state.script.estimated_duration_minutes
        detail = []
        if words:
            detail.append(f"{words} words")
        if duration:
            detail.append(f"≈{duration} min narration")
        suffix = f" ({', '.join(detail)})" if detail else ""
        print(f"Script: {state.script.title}{suffix}")

    if state.fact_check is not None:
        print(
            f"Fact check: {'PASS' if state.fact_check.approved else 'BLOCKED'} "
            f"({state.fact_check.score:.0f}/100)"
        )

    if state.video_assembly is not None:
        artifact = state.video_assembly.artifact
        duration = _duration_label(artifact.duration_seconds)
        suffix = f" ({duration})" if duration else ""
        print(f"Video: {artifact.file_path}{suffix}")

    if state.thumbnail_generation is not None:
        print(f"Thumbnail: {state.thumbnail_generation.artifact.file_path}")

    if result_path is not None:
        print(f"Full result JSON: {result_path}")
