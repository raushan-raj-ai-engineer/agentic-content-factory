from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

_TREATMENTS: tuple[tuple[str, str, str], ...] = (
    (
        "opening_context",
        "editorial opening context with one strong focal subject and supporting context",
        "clear focal hierarchy; avoid the same centered composition used in adjacent scenes",
    ),
    (
        "evidence_board",
        "evidence-led visual board using only claims already present in the script or research",
        "source/context hierarchy with 2-3 distinct evidence zones; no invented quote or statistic",
    ),
    (
        "timeline",
        "chronological timeline treatment when chronology is supported, otherwise ordered key-point progression",
        "left-to-right progression with clearly separated beats; no fabricated dates",
    ),
    (
        "comparison_split",
        "split-screen comparison of two script-supported ideas, teams, viewpoints, or contexts",
        "asymmetric two-panel composition; use only supported comparisons",
    ),
    (
        "headline_context",
        "news-context treatment that visually separates the confirmed headline from explanatory context",
        "editorial headline zone plus contextual imagery; no fake newspaper branding or fake quotes",
    ),
    (
        "key_points",
        "key-points explainer with several visually distinct supporting elements",
        "modular visual hierarchy instead of one full-frame illustration; no dense paragraphs",
    ),
    (
        "what_to_watch",
        "forward-looking watch-list treatment limited to explicitly stated uncertainties or next things to monitor",
        "three-part watch-list layout; label uncertainty clearly; do not predict unsupported outcomes",
    ),
    (
        "closing_synthesis",
        "closing synthesis that visually reconnects the strongest confirmed ideas from earlier scenes",
        "recap composition with a new layout; do not reuse the opening scene composition",
    ),
)

_MARKER_RE = re.compile(r"CF_TREATMENT:([a-z0-9_]+)", re.I)


def _safe_get(obj: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def _safe_set(obj: Any, name: str, value: Any) -> bool:
    try:
        setattr(obj, name, value)
        return True
    except Exception:
        return False


def _append_text(obj: Any, field: str, addition: str) -> None:
    current = _safe_get(obj, field, None)
    if isinstance(current, str):
        if addition not in current:
            _safe_set(obj, field, (current.rstrip() + " " + addition).strip())


def _append_avoid(obj: Any, values: list[str]) -> None:
    current = _safe_get(obj, "avoid", None)
    if isinstance(current, list):
        merged = list(current)
        for value in values:
            if value not in merged:
                merged.append(value)
        _safe_set(obj, "avoid", merged)


def _script_text(state: Any) -> str:
    script = _safe_get(state, "script", None)
    if script is None:
        return ""
    try:
        data = script.model_dump()
    except Exception:
        try:
            data = vars(script)
        except Exception:
            return str(script)

    parts: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    walk(data)
    return " ".join(parts)


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'’-]+\b", text, flags=re.UNICODE))


def _scene_text(scene: Any) -> str:
    fields = ("title", "description", "style", "composition", "subject", "visual_type")
    return " ".join(str(_safe_get(scene, field, "") or "") for field in fields)


def treatment_names(state: Any) -> list[str]:
    plan = _safe_get(state, "production_plan", None)
    scenes = list(_safe_get(plan, "visual_scenes", []) or []) if plan is not None else []
    names: list[str] = []
    for scene in scenes:
        match = _MARKER_RE.search(_scene_text(scene))
        if match:
            names.append(match.group(1).lower())
    return names


def readiness_metrics(state: Any) -> dict[str, Any]:
    plan = _safe_get(state, "production_plan", None)
    scenes = list(_safe_get(plan, "visual_scenes", []) or []) if plan is not None else []
    words = _word_count(_script_text(state))
    treatments = treatment_names(state)
    visual_types = {
        str(_safe_get(scene, "visual_type", "") or "").strip().lower()
        for scene in scenes
        if str(_safe_get(scene, "visual_type", "") or "").strip()
    }
    scene_signatures = {
        re.sub(r"\s+", " ", str(_safe_get(scene, "description", "") or "").strip().lower())[:180]
        for scene in scenes
        if str(_safe_get(scene, "description", "") or "").strip()
    }
    unique_scene_ratio = (len(scene_signatures) / len(scenes)) if scenes else 0.0
    return {
        "narration_words": words,
        "scene_count": len(scenes),
        "unique_treatments": len(set(treatments)),
        "treatments": treatments,
        "unique_visual_types": len(visual_types),
        "unique_scene_ratio": round(unique_scene_ratio, 3),
    }


def _minimum_narration_words(state: Any) -> int:
    """Internal narration floor scaled to the actual generated duration.

    This is a local quality heuristic, not a platform rule. It prevents a
    genuine short video from being rejected solely for not reaching a long-form
    word count.
    """
    actual_minutes = 0
    metadata = _safe_get(state, "metadata", None)
    if isinstance(metadata, dict):
        length = metadata.get("script_length")
        if isinstance(length, dict):
            try:
                actual_minutes = int(length.get("actual_minutes", 0) or 0)
            except (TypeError, ValueError):
                actual_minutes = 0

    if actual_minutes <= 0:
        words = _word_count(_script_text(state))
        actual_minutes = max(1, round(words / 165)) if words else 1

    return max(180, min(450, actual_minutes * 110))


def materially_varied(state: Any) -> bool:
    """Conservative exception to a same-renderer heuristic.

    A single image-generation backend is not automatically the same thing as
    repetitive/mass-produced content. We only return True when there is strong
    original narration plus scene-by-scene editorial variation.
    """
    metrics = readiness_metrics(state)
    return bool(
        metrics["narration_words"] >= _minimum_narration_words(state)
        and metrics["scene_count"] >= 6
        and metrics["unique_treatments"] >= 4
        and metrics["unique_scene_ratio"] >= 0.65
    )


def prepare_plan_for_monetization(plan: Any, state: Any) -> Any:
    """Add scene-specific editorial treatment directives without inventing facts."""
    if plan is None:
        return plan
    scenes = list(_safe_get(plan, "visual_scenes", []) or [])
    if not scenes:
        return plan

    for index, scene in enumerate(scenes):
        name, style, composition = _TREATMENTS[index % len(_TREATMENTS)]
        marker = f"CF_TREATMENT:{name}"
        _append_text(scene, "style", f"{marker}. {style}.")
        _append_text(scene, "composition", composition + ".")
        _append_text(
            scene,
            "description",
            "Use a scene-specific editorial treatment distinct from the previous scene; "
            "show only information supported by the approved script/research.",
        )
        _append_avoid(
            scene,
            [
                "same composition as the previous scene",
                "repetitive full-frame slideshow treatment",
                "invented statistics or quotes",
                "copied broadcast graphics or watermarks",
            ],
        )

    try:
        metadata = _safe_get(state, "metadata", None)
        if isinstance(metadata, dict):
            metadata["monetization_preflight"] = readiness_metrics(state)
            metadata["monetization_preflight"]["ai_disclosure_review_required"] = True
    except Exception:
        pass

    metrics = readiness_metrics(state)
    print(
        "[MONETIZATION PREFLIGHT V20.2] "
        f"words={metrics['narration_words']}; min_words={_minimum_narration_words(state)}; scenes={metrics['scene_count']}; "
        f"treatments={metrics['unique_treatments']}; unique_scene_ratio={metrics['unique_scene_ratio']:.2f}"
    )
    return plan


def _find_run_root(state: Any) -> Path | None:
    metadata = _safe_get(state, "metadata", None)
    if isinstance(metadata, dict):
        for key in ("artifact_root", "run_dir", "output_dir", "artifacts_dir"):
            value = metadata.get(key)
            if isinstance(value, str) and value:
                path = Path(value).expanduser()
                if path.exists():
                    return path

    run_id = str(_safe_get(state, "run_id", "") or "").replace("-", "")
    prefix = run_id[:12]
    root = Path(os.getenv("CONTENT_FACTORY_ARTIFACTS", "artifacts")).expanduser()
    if root.exists() and prefix:
        candidates = [p for p in root.glob(f"**/{prefix}*") if p.is_dir()]
        if candidates:
            return max(candidates, key=lambda p: p.stat().st_mtime)
    return None


def finalize_monetization_artifacts(state: Any) -> None:
    """Write a truthful disclosure review and preflight report.

    This does not auto-claim that YouTube disclosure is always required. It
    makes the uploader review realistic synthetic scenes explicitly.
    """
    run_root = _find_run_root(state)
    if run_root is None:
        return
    out_dir = run_root / "monetization"
    out_dir.mkdir(parents=True, exist_ok=True)

    metrics = readiness_metrics(state)
    metrics["materially_varied"] = materially_varied(state)
    (out_dir / "monetization_preflight_v20_2.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    disclosure = """# AI / Synthetic Content Disclosure Review\n\nThis pipeline uses AI-assisted/generated visuals and synthetic narration.\n\nBefore upload, review the final video scene by scene:\n\n- If a generated scene looks realistic and depicts a real person, real match/event, or real place doing/showing something that did not actually happen, select **Yes** for YouTube Studio's AI-use / altered-or-synthetic disclosure.\n- If the visuals are clearly non-realistic illustrations/animations or AI was used only for production assistance, disclosure may not be required under YouTube's current guidance.\n- Never use a disclosure label as permission to fabricate facts, impersonate a real person, or reuse protected broadcast footage.\n\nThis file is a review requirement, not an automatic Yes/No decision.\n"""
    (out_dir / "AI_DISCLOSURE_REVIEW.md").write_text(disclosure, encoding="utf-8")

    checklist = out_dir / "YOUTUBE_UPLOAD_CHECKLIST.md"
    section = """\n\n## V20.2 authenticity / AI review\n\n- [ ] Final narration contains original commentary/explanation, not generic filler.\n- [ ] Scene treatments are materially varied rather than one repeated template.\n- [ ] No invented statistics, quotes, match events, or unsupported predictions.\n- [ ] No copied broadcast footage, watermarks, or unlicensed highlight clips.\n- [ ] Reviewed `AI_DISCLOSURE_REVIEW.md` and selected the YouTube AI-use setting truthfully.\n"""
    if checklist.exists():
        text = checklist.read_text(encoding="utf-8", errors="replace")
        if "## V20.2 authenticity / AI review" not in text:
            checklist.write_text(text.rstrip() + section + "\n", encoding="utf-8")
    else:
        checklist.write_text("# YouTube Upload Checklist" + section + "\n", encoding="utf-8")

    print(
        "[MONETIZATION V20.2] "
        f"materially_varied={'YES' if metrics['materially_varied'] else 'NO'}; "
        f"disclosure_review={out_dir / 'AI_DISCLOSURE_REVIEW.md'}"
    )
