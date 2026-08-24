from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import uuid
import time
from datetime import datetime, timezone
from pathlib import Path

from content_factory.cartoon.characters import (
    character_registry,
    default_cast,
)
from content_factory.cartoon.language import (
    available_languages,
    load_language_pack,
)
from content_factory.cartoon.llm import CartoonLLMProvider
from content_factory.cartoon.models import CartoonEpisodePlan
from content_factory.cartoon.monetization import (
    BLOCK,
    REVIEW,
    print_gate_logs,
    run_post_render_gate,
    run_pre_render_gate,
    write_gate_report,
)
from content_factory.cartoon.renderer import CartoonRenderer
from content_factory.cartoon.story_planner import CartoonStoryPlanner
from content_factory.cartoon.router import resolve_story_profile
from content_factory.cartoon.channel_profiles import resolve_channel_name


from content_factory.cartoon.model_selection import project_root_from_cli, resolve_model

def _slug(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(
        r"[^\w\u0900-\u097f]+",
        "-",
        value,
        flags=re.UNICODE,
    )
    value = re.sub(r"-+", "-", value).strip("-")
    return value[:70] or "cartoon-episode"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "V11.1 production-performance universal cartoon + intent grounding + strict monetization gate. "
            "Creates a quality-guarded episode plan and renders an original "
            "limited-animation 1080p24 MP4."
        )
    )
    parser.add_argument(
        "--topic",
        required=False,
        help="Comedy topic/premise.",
    )
    parser.add_argument(
        "--channel",
        choices=("auto", "hindi_mass", "global_english"),
        default="auto",
        help="Content channel profile. auto: English->global_english, other supported languages->hindi_mass.",
    )
    parser.add_argument(
        "--language",
        default="hindi",
        help=(
            "english, hindi, hinglish, magahi or bhojpuri "
            "(aliases en/hi supported)."
        ),
    )
    parser.add_argument(
        "--minutes",
        type=int,
        default=3,
        help="Target episode duration, 1-6 minutes.",
    )
    parser.add_argument(
        "--cast",
        default="",
        help=(
            "Comma-separated house character IDs. "
            "Default: guddu,bittu,chacha,mai,babuji."
        ),
    )
    parser.add_argument(
        "--story-only",
        action="store_true",
        help="Create episode_plan.json but skip MP4 rendering.",
    )
    parser.add_argument(
        "--render-plan",
        default="",
        help=(
            "Render an existing episode_plan.json without calling the LLM. "
            "Relative paths are resolved from the project root."
        ),
    )
    parser.add_argument(
        "--monetization-mode",
        choices=("strict", "report", "off"),
        default=os.getenv("CONTENT_FACTORY_MONETIZATION_MODE", "strict"),
        help=(
            "strict=block expensive render on pre-render BLOCK; "
            "report=always render but report readiness; off=disable gate."
        ),
    )
    parser.add_argument(
        "--allow-blocked-render",
        action="store_true",
        help=(
            "In strict mode, render even when the pre-render monetization "
            "gate says BLOCK_UPLOAD. Upload readiness remains NO."
        ),
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Local Ollama model. Highest-priority explicit override. "
            "When omitted: terminal env > .env > configs/local.yaml > built-in default."
        ),
    )
    parser.add_argument("--list-languages", action="store_true")
    parser.add_argument("--list-characters", action="store_true")
    args = parser.parse_args()
    selection = resolve_model(
        project_root=project_root_from_cli(__file__),
        cli_model=args.model,
    )
    args.model = selection.model
    args.model_source = selection.source
    args.model_source_key = selection.key
    return args


def _write_run_info(*, path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_perf_report(
    *,
    artifact_root: Path,
    payload: dict[str, object],
) -> Path:
    perf_dir = artifact_root / "performance"
    perf_dir.mkdir(parents=True, exist_ok=True)
    path = perf_dir / "performance_report.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def _decision_status(decision: str) -> str:
    if decision == BLOCK:
        return "video_rendered_blocked_upload"
    if decision == REVIEW:
        return "video_rendered_review_required"
    return "video_rendered"


def _render_existing_plan(
    *,
    args: argparse.Namespace,
    project_root: Path,
) -> int:
    total_start = time.perf_counter()
    raw = Path(args.render_plan).expanduser()
    plan_path = (
        raw.resolve()
        if raw.is_absolute()
        else (project_root / raw).resolve()
    )
    if not plan_path.is_file():
        raise SystemExit(f"--render-plan file not found: {plan_path}")

    plan = CartoonEpisodePlan.model_validate_json(
        plan_path.read_text(encoding="utf-8")
    )
    language = load_language_pack(plan.language_code)
    channel_name = resolve_channel_name(args.channel, language.code)
    os.environ["CONTENT_FACTORY_CARTOON_CHANNEL"] = channel_name
    print(f"[CARTOON CHANNEL V17.7] mode=render-existing-plan; channel={channel_name}; language={language.code}")

    if plan_path.parent.name == "story":
        artifact_root = plan_path.parent.parent
    else:
        render_run_id = uuid.uuid4().hex[:12]
        artifact_root = (
            project_root
            / "artifacts"
            / "cartoon"
            / _slug(plan.topic)
            / render_run_id
        )
        story_dir = artifact_root / "story"
        story_dir.mkdir(parents=True, exist_ok=True)
        copied_plan = story_dir / "episode_plan.json"
        copied_plan.write_text(
            plan.model_dump_json(indent=2),
            encoding="utf-8",
        )
        plan_path = copied_plan

    print("[CARTOON V11.1] mode=render-existing-plan; LLM calls=0.")
    try:
        relative_plan = plan_path.relative_to(project_root)
    except ValueError:
        relative_plan = plan_path
    print(f"[CARTOON V11.1] Plan: {relative_plan}")

    # V17.8 public-quality gate: validate story semantics even when the user
    # supplies --render-plan. This prevents a structurally valid but off-premise
    # or generic plan from consuming a full render.
    _v178_weak = (
        CartoonStoryPlanner.v178_plan_weak_reasons(plan=plan, language=language)
        if channel_name == "hindi_mass"
        else {}
    )
    _v178_force = os.getenv("CONTENT_FACTORY_CARTOON_RENDER_WEAK_STORY", "0").strip().lower() in {"1", "true", "yes", "on"}
    if _v178_weak and not _v178_force:
        _write_run_info(
            path=artifact_root / "run_info.json",
            payload={
                "status": "story_quality_blocked_existing_plan",
                "final_video_generated": False,
                "upload_ready": False,
                "weak_story_scene_ids": sorted(_v178_weak),
                "weak_story_reasons": {str(k): v for k, v in _v178_weak.items()},
                "rendered_from_plan": str(relative_plan),
            },
        )
        print(
            "[CARTOON STORY GATE V17.8] render=BLOCKED_WEAK_EXISTING_PLAN; "
            f"weak_scenes={sorted(_v178_weak)}; reasons={_v178_weak}; "
            "override=CONTENT_FACTORY_CARTOON_RENDER_WEAK_STORY=1"
        )
        return 0


    pre_gate = None
    pre_gate_path = None
    pre_gate_seconds = 0.0

    if args.monetization_mode != "off":
        gate_start = time.perf_counter()
        pre_gate = run_pre_render_gate(
            project_root=project_root,
            plan=plan,
            plan_path=plan_path,
        )
        pre_gate_seconds = time.perf_counter() - gate_start
        pre_gate_path = write_gate_report(
            artifact_root=artifact_root,
            filename="monetization_pre.json",
            result=pre_gate,
        )
        print_gate_logs(pre_gate)

        if (
            args.monetization_mode == "strict"
            and pre_gate.decision == BLOCK
            and not args.allow_blocked_render
        ):
            run_info = {
                "status": "blocked_before_render",
                "final_video_generated": False,
                "upload_ready": False,
                "monetization_decision": pre_gate.decision,
                "monetization_pre_report": str(
                    pre_gate_path.relative_to(project_root)
                ),
                "rendered_from_plan": str(relative_plan),
            }
            _write_run_info(
                path=artifact_root / "run_info.json",
                payload=run_info,
            )
            perf_path = _write_perf_report(
                artifact_root=artifact_root,
                payload={
                    "version": "9.3",
                    "mode": "render_existing_plan",
                    "llm_calls": 0,
                    "pre_gate_seconds": round(pre_gate_seconds, 4),
                    "render_seconds": 0.0,
                    "post_gate_seconds": 0.0,
                    "total_seconds": round(
                        time.perf_counter() - total_start,
                        4,
                    ),
                    "render_skipped_by_strict_gate": True,
                    "quality_settings_changed": False,
                },
            )
            print(
                "[PERF V9.3] render skipped by strict BLOCK; "
                f"report={perf_path.relative_to(project_root)}"
            )
            print("[CARTOON V11.1] Status: blocked_before_render")
            return 3

    render_start = time.perf_counter()
    renderer = CartoonRenderer(
        project_root=project_root,
        language=language,
    )
    result = renderer.render(
        plan=plan,
        artifact_root=artifact_root,
    )
    render_seconds = time.perf_counter() - render_start

    post_gate = pre_gate
    final_gate_path = pre_gate_path
    post_gate_seconds = 0.0

    if args.monetization_mode != "off" and pre_gate is not None:
        gate_start = time.perf_counter()
        post_gate = run_post_render_gate(
            project_root=project_root,
            plan=plan,
            plan_path=plan_path,
            render_report_path=result.report_path,
            master_audio_path=result.master_audio,
            pre_result=pre_gate,
        )
        post_gate_seconds = time.perf_counter() - gate_start
        final_gate_path = write_gate_report(
            artifact_root=artifact_root,
            filename="monetization_report.json",
            result=post_gate,
        )
        print_gate_logs(post_gate)

    upload_ready = (
        bool(post_gate.upload_ready)
        if post_gate is not None
        else False
    )
    monetization_decision = (
        post_gate.decision
        if post_gate is not None
        else "DISABLED"
    )

    run_info_path = artifact_root / "run_info.json"
    run_info: dict[str, object] = {}
    if run_info_path.is_file():
        try:
            run_info = json.loads(
                run_info_path.read_text(encoding="utf-8")
            )
        except Exception:
            run_info = {}

    status = (
        _decision_status(monetization_decision)
        if args.monetization_mode != "off"
        else "video_rendered_monetization_disabled"
    )
    run_info.update(
        {
            "status": status,
            "final_video_generated": True,
            "last_rendered_at_utc": datetime.now(timezone.utc).isoformat(),
            "final_video": str(result.final_video.relative_to(project_root)),
            "master_audio": str(result.master_audio.relative_to(project_root)),
            "render_report": str(result.report_path.relative_to(project_root)),
            "render_degraded": result.degraded,
            "final_video_seconds": round(result.duration_seconds, 3),
            "rendered_from_plan": str(relative_plan),
            "upload_ready": upload_ready,
            "monetization_mode": args.monetization_mode,
            "monetization_decision": monetization_decision,
            "monetization_report": (
                str(final_gate_path.relative_to(project_root))
                if final_gate_path is not None
                else None
            ),
        }
    )

    perf_path = _write_perf_report(
        artifact_root=artifact_root,
        payload={
            "version": "9.3",
            "mode": "render_existing_plan",
            "llm_calls": 0,
            "pre_gate_seconds": round(pre_gate_seconds, 4),
            "render_seconds": round(render_seconds, 4),
            "post_gate_seconds": round(post_gate_seconds, 4),
            "total_seconds": round(
                time.perf_counter() - total_start,
                4,
            ),
            "render_skipped_by_strict_gate": False,
            "quality_settings_changed": False,
            "quality_preserving_optimizations": [
                "persistent story fingerprint index",
                "single-pass WAV audio quality scan",
                "no LLM monetization calls",
                "strict pre-gate can skip wasted render",
            ],
        },
    )
    run_info["performance_report"] = str(
        perf_path.relative_to(project_root)
    )
    _write_run_info(path=run_info_path, payload=run_info)

    print(
        "[PERF V9.3] "
        f"pre_gate={pre_gate_seconds:.3f}s, "
        f"render={render_seconds:.3f}s, "
        f"post_gate={post_gate_seconds:.3f}s, "
        f"total={time.perf_counter() - total_start:.3f}s"
    )
    print(
        f"[CARTOON V11.1] Status: {status}; "
        f"Upload Ready: {'YES' if upload_ready else 'NO'}"
    )
    return 0




async def _run(args: argparse.Namespace) -> int:
    total_start = time.perf_counter()
    project_root = Path(__file__).resolve().parents[3]

    if args.list_languages:
        print("\n".join(available_languages()))
        return 0

    if args.list_characters:
        for item in character_registry().values():
            print(f"{item.id:<10} {item.display_name:<12} {item.role}")
        return 0

    if args.render_plan:
        return _render_existing_plan(
            args=args,
            project_root=project_root,
        )

    if not args.topic:
        raise SystemExit(
            "--topic is required unless using --list-languages, "
            "--list-characters, or --render-plan."
        )

    language = load_language_pack(args.language)
    channel_name = resolve_channel_name(args.channel, language.code)
    os.environ["CONTENT_FACTORY_CARTOON_CHANNEL"] = channel_name
    print(f"[CARTOON CHANNEL V15] channel={channel_name}; language={language.code}")
    if channel_name == "hindi_mass":
        print("[INDIAN COMEDY V15] trend-aware original comedy=ON; recurring personalities=ON; trend cache=12h; unsafe trends=FILTERED")
    minutes = max(1, min(int(args.minutes), 6))
    explicit_cast = [
        item.strip()
        for item in args.cast.split(",")
        if item.strip()
    ]
    profile_preview = resolve_story_profile(
        topic=args.topic,
        language_code=language.code,
    )
    registry = character_registry()
    auto_cast = [
        str(item)
        for item in profile_preview.get("preferred_cast", [])
        if str(item) in registry
    ][:5]
    if len(auto_cast) < 2:
        auto_cast = default_cast(limit=5)

    planner_cast = explicit_cast if explicit_cast else None
    cast_preview = explicit_cast if explicit_cast else auto_cast
    cast_source = "explicit" if explicit_cast else "auto-topic"

    print(
        "[CARTOON V11.1] "
        f"language={language.code}/{language.display_name}, "
        f"minutes={minutes}, cast_source={cast_source}, "
        f"cast={','.join(cast_preview)}"
    )
    print(
        "[CARTOON V11.1] "
        "mode=story+render; intent-grounded planning + articulated renderer + strict monetization gate + "
        "quality-preserving renderer."
    )

    cartoon_timeout = float(
        os.getenv(
            "CONTENT_FACTORY_CARTOON_LLM_TIMEOUT",
            os.getenv("CONTENT_FACTORY_LLM_TIMEOUT", "600"),
        )
    )
    print(
        "[CARTOON MODEL] "
        f"model={args.model}; "
        f"source={getattr(args, 'model_source', 'unknown')}; "
        f"key={getattr(args, 'model_source_key', None) or '-'}"
    )

    print(
        "[CARTOON V9] "
        f"Local model={args.model}, per-call timeout={cartoon_timeout:.0f}s"
    )

    llm = CartoonLLMProvider(
        model=args.model,
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        timeout=cartoon_timeout,
    )
    planner = CartoonStoryPlanner(llm)
    tuning = llm.tuning()
    print(
        "[CARTOON PERF] "
        f"num_ctx={tuning['num_ctx']}, "
        f"num_predict={tuning['num_predict']}, "
        f"num_thread={tuning['num_thread']}"
    )
    print(
        "[CARTOON V9] Starting deterministic story skeleton + "
        "compact dialogue batches..."
    )

    planner_error = None
    planning_start = time.perf_counter()
    llm_stats_snapshot: dict[str, object] = {}
    try:
        try:
            plan = await planner.create_plan(
                topic=args.topic,
                language=language,
                target_minutes=minutes,
                cast=planner_cast,
            )
        except Exception as exc:
            planner_error = f"{type(exc).__name__}: {str(exc)[:500]}"
            print(
                "[CARTOON RECOVERY] Unexpected planner error; using full "
                "deterministic episode fallback instead of failing."
            )
            plan = CartoonStoryPlanner.create_fallback_plan(
                topic=args.topic,
                language=language,
                target_minutes=minutes,
                cast=cast_preview,
            )
    finally:
        stats = llm.stats()
        llm_stats_snapshot = dict(stats)
        print(
            "[CARTOON PERF] "
            f"requests={int(stats.get('requests', 0))}, "
            f"prompt_eval={float(stats.get('prompt_eval_seconds', 0.0)):.1f}s, "
            f"generation={float(stats.get('ollama_eval_seconds', 0.0)):.1f}s"
        )
        await llm.release()

    planning_seconds = time.perf_counter() - planning_start

    run_id = uuid.uuid4().hex[:12]
    artifact_root = (
        project_root
        / "artifacts"
        / "cartoon"
        / _slug(args.topic)
        / run_id
    )
    story_dir = artifact_root / "story"
    story_dir.mkdir(parents=True, exist_ok=True)
    output = story_dir / "episode_plan.json"
    output.write_text(
        plan.model_dump_json(indent=2),
        encoding="utf-8",
    )

    recovery_report = dict(planner.last_report or {})
    if planner_error is not None:
        recovery_report["planner_error"] = planner_error
        recovery_report["degraded"] = True
        recovery_report["mode"] = "emergency_fallback"

    recovery_report_path = story_dir / "recovery_report.json"
    recovery_report_path.write_text(
        json.dumps(recovery_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    run_info: dict[str, object] = {
        "run_id": run_id,
        "mode": "cartoon_v9_3_monetization_strict",
        "topic": args.topic,
        "language": language.code,
        "language_name": language.display_name,
        "channel": channel_name,
        "target_minutes": minutes,
        "cast": list(plan.characters),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "story_planned",
        "final_video_generated": False,
        "degraded": bool(recovery_report.get("degraded", False)),
        "recovery_report": str(
            recovery_report_path.relative_to(project_root)
        ),
        "episode_plan": str(output.relative_to(project_root)),
    }

    print(f"[CARTOON V9] Scenes: {len(plan.scenes)}")
    print(
        "[CARTOON V9] Episode plan: "
        f"{output.relative_to(project_root)}"
    )
    print(
        "[CARTOON V9] Recovery report: "
        f"{recovery_report_path.relative_to(project_root)}"
    )

    pre_gate = None
    pre_gate_path = None
    pre_gate_seconds = 0.0

    if args.monetization_mode != "off":
        gate_start = time.perf_counter()
        pre_gate = run_pre_render_gate(
            project_root=project_root,
            plan=plan,
            plan_path=output,
        )
        pre_gate_seconds = time.perf_counter() - gate_start
        pre_gate_path = write_gate_report(
            artifact_root=artifact_root,
            filename="monetization_pre.json",
            result=pre_gate,
        )
        print_gate_logs(pre_gate)
        run_info.update(
            {
                "monetization_mode": args.monetization_mode,
                "monetization_pre_decision": pre_gate.decision,
                "monetization_pre_report": str(
                    pre_gate_path.relative_to(project_root)
                ),
                "made_for_kids": pre_gate.made_for_kids,
                "ai_disclosure": pre_gate.ai_disclosure,
                "upload_ready": False,
            }
        )
    else:
        run_info.update(
            {
                "monetization_mode": "off",
                "monetization_pre_decision": "DISABLED",
                "upload_ready": False,
            }
        )

    _weak_ids = list(recovery_report.get("weak_story_scene_ids", []) or [])
    _fallback_count = int(recovery_report.get("fallback_scenes", 0) or 0)
    _story_quality = str(recovery_report.get("story_quality_status", "") or "")
    _scene_count = max(1, len(plan.scenes))
    # strict_semantic_story_gate_v17_8
    _catastrophic_story = (
        channel_name == "hindi_mass"
        and _story_quality == "REVIEW_REQUIRED"
        and (bool(_weak_ids) or _fallback_count > 0)
    )
    _force_weak_render = os.getenv("CONTENT_FACTORY_CARTOON_RENDER_WEAK_STORY", "0").strip().lower() in {"1", "true", "yes", "on"}
    if _catastrophic_story and not args.story_only and not _force_weak_render:
        run_info.update({
            "status": "story_quality_blocked_render",
            "final_video_generated": False,
            "upload_ready": False,
        })
        _write_run_info(path=artifact_root / "run_info.json", payload=run_info)
        print(
            "[CARTOON STORY GATE V17.7] render=BLOCKED_WEAK_STORY; "
            f"fallback_scenes={_fallback_count}; weak_scenes={_weak_ids}; "
            "reason=protect_time_and_public_quality; override=CONTENT_FACTORY_CARTOON_RENDER_WEAK_STORY=1"
        )
        return 0

    if args.story_only:
        run_info["status"] = (
            "story_planned"
            if pre_gate is None or pre_gate.decision == "PASS"
            else (
                "story_planned_blocked_upload"
                if pre_gate.decision == BLOCK
                else "story_planned_review_required"
            )
        )
        perf_path = _write_perf_report(
            artifact_root=artifact_root,
            payload={
                "version": "9.3",
                "mode": "story_only",
                "planning_seconds": round(planning_seconds, 4),
                "pre_gate_seconds": round(pre_gate_seconds, 4),
                "render_seconds": 0.0,
                "post_gate_seconds": 0.0,
                "total_seconds": round(
                    time.perf_counter() - total_start,
                    4,
                ),
                "llm_requests": int(
                    llm_stats_snapshot.get("requests", 0)
                ),
                "quality_settings_changed": False,
            },
        )
        run_info["performance_report"] = str(
            perf_path.relative_to(project_root)
        )
        _write_run_info(
            path=artifact_root / "run_info.json",
            payload=run_info,
        )
        print(
            "[PERF V9.3] "
            f"planning={planning_seconds:.3f}s, "
            f"pre_gate={pre_gate_seconds:.3f}s, "
            f"total={time.perf_counter() - total_start:.3f}s"
        )
        print("[CARTOON V11.1] Status: story_planned (--story-only)")
        return 0

    if (
        args.monetization_mode == "strict"
        and pre_gate is not None
        and pre_gate.decision == BLOCK
        and not args.allow_blocked_render
    ):
        run_info.update(
            {
                "status": "blocked_before_render",
                "final_video_generated": False,
                "upload_ready": False,
                "monetization_decision": pre_gate.decision,
            }
        )
        perf_path = _write_perf_report(
            artifact_root=artifact_root,
            payload={
                "version": "9.3",
                "mode": "story_plus_render",
                "planning_seconds": round(planning_seconds, 4),
                "pre_gate_seconds": round(pre_gate_seconds, 4),
                "render_seconds": 0.0,
                "post_gate_seconds": 0.0,
                "total_seconds": round(
                    time.perf_counter() - total_start,
                    4,
                ),
                "llm_requests": int(
                    llm_stats_snapshot.get("requests", 0)
                ),
                "render_skipped_by_strict_gate": True,
                "quality_settings_changed": False,
            },
        )
        run_info["performance_report"] = str(
            perf_path.relative_to(project_root)
        )
        _write_run_info(
            path=artifact_root / "run_info.json",
            payload=run_info,
        )
        print(
            "[PERF V9.3] strict BLOCK prevented expensive 1080p render."
        )
        print("[CARTOON V11.1] Status: blocked_before_render")
        return 3

    render_start = time.perf_counter()
    renderer = CartoonRenderer(
        project_root=project_root,
        language=language,
    )
    render_result = renderer.render(
        plan=plan,
        artifact_root=artifact_root,
    )
    render_seconds = time.perf_counter() - render_start

    post_gate = pre_gate
    final_gate_path = pre_gate_path
    post_gate_seconds = 0.0

    if args.monetization_mode != "off" and pre_gate is not None:
        gate_start = time.perf_counter()
        post_gate = run_post_render_gate(
            project_root=project_root,
            plan=plan,
            plan_path=output,
            render_report_path=render_result.report_path,
            master_audio_path=render_result.master_audio,
            pre_result=pre_gate,
        )
        post_gate_seconds = time.perf_counter() - gate_start
        final_gate_path = write_gate_report(
            artifact_root=artifact_root,
            filename="monetization_report.json",
            result=post_gate,
        )
        print_gate_logs(post_gate)

    upload_ready = (
        bool(post_gate.upload_ready)
        if post_gate is not None
        else False
    )
    monetization_decision = (
        post_gate.decision
        if post_gate is not None
        else "DISABLED"
    )

    run_info.update(
        {
            "status": "video_rendered",
            "final_video_generated": True,
            "final_video": str(
                render_result.final_video.relative_to(project_root)
            ),
            "master_audio": str(
                render_result.master_audio.relative_to(project_root)
            ),
            "render_report": str(
                render_result.report_path.relative_to(project_root)
            ),
            "render_degraded": render_result.degraded,
            "final_video_seconds": round(
                render_result.duration_seconds,
                3,
            ),
            "upload_ready": upload_ready,
            "monetization_decision": monetization_decision,
            "monetization_report": (
                str(final_gate_path.relative_to(project_root))
                if final_gate_path is not None
                else None
            ),
            "made_for_kids": (
                post_gate.made_for_kids
                if post_gate is not None
                else None
            ),
            "ai_disclosure": (
                post_gate.ai_disclosure
                if post_gate is not None
                else "DISABLED"
            ),
        }
    )
    run_info["status"] = (
        _decision_status(monetization_decision)
        if args.monetization_mode != "off"
        else "video_rendered_monetization_disabled"
    )
    perf_path = _write_perf_report(
        artifact_root=artifact_root,
        payload={
            "version": "9.3",
            "mode": "story_plus_render",
            "planning_seconds": round(planning_seconds, 4),
            "llm_requests": int(
                llm_stats_snapshot.get("requests", 0)
            ),
            "llm_prompt_eval_seconds": round(
                float(
                    llm_stats_snapshot.get(
                        "prompt_eval_seconds",
                        0.0,
                    )
                ),
                4,
            ),
            "llm_generation_seconds": round(
                float(
                    llm_stats_snapshot.get(
                        "ollama_eval_seconds",
                        0.0,
                    )
                ),
                4,
            ),
            "pre_gate_seconds": round(pre_gate_seconds, 4),
            "render_seconds": round(render_seconds, 4),
            "post_gate_seconds": round(post_gate_seconds, 4),
            "total_seconds": round(
                time.perf_counter() - total_start,
                4,
            ),
            "render_skipped_by_strict_gate": False,
            "quality_settings_changed": False,
            "quality_preserving_optimizations": [
                "persistent story fingerprint index",
                "single-pass WAV audio quality scan",
                "no LLM monetization calls",
                "strict pre-gate can skip wasted render",
                "renderer encoder/resolution/fps/voice mastering unchanged",
            ],
        },
    )
    run_info["performance_report"] = str(
        perf_path.relative_to(project_root)
    )
    _write_run_info(
        path=artifact_root / "run_info.json",
        payload=run_info,
    )

    print(
        "[PERF V9.3] "
        f"planning={planning_seconds:.3f}s, "
        f"pre_gate={pre_gate_seconds:.3f}s, "
        f"render={render_seconds:.3f}s, "
        f"post_gate={post_gate_seconds:.3f}s, "
        f"total={time.perf_counter() - total_start:.3f}s"
    )
    print(
        f"[CARTOON V11.1] Status: {run_info['status']}; "
        f"Upload Ready: {'YES' if upload_ready else 'NO'}"
    )
    return 0


def main() -> None:
    args = _parse_args()
    try:
        code = asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("\n[CARTOON V11.1] Stopped by user.", file=sys.stderr)
        raise SystemExit(130)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
