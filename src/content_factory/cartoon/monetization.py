from __future__ import annotations

import hashlib
import json
import math
import re
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from content_factory.cartoon.models import CartoonEpisodePlan


PASS = "PASS"
REVIEW = "REVIEW_REQUIRED"
BLOCK = "BLOCK_UPLOAD"


@dataclass(frozen=True)
class GateResult:
    decision: str
    upload_ready: bool
    made_for_kids: bool | None
    ai_disclosure: str
    report: dict[str, object]


def _root_from_module() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_policy(project_root: Path) -> dict[str, object]:
    path = project_root / "configs" / "cartoon_monetization.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _norm(value: str) -> str:
    value = (value or "").casefold()
    value = re.sub(r"[^\w\u0900-\u097f]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def _contains_any(text: str, terms: Iterable[str]) -> list[str]:
    value = _norm(text)
    hits: list[str] = []
    for term in terms:
        token = _norm(str(term))
        if not token:
            continue
        pattern = (
            r"(?<![\w\u0900-\u097f])"
            + re.escape(token).replace(r"\ ", r"\s+")
            + r"(?![\w\u0900-\u097f])"
        )
        if re.search(pattern, value, flags=re.UNICODE):
            hits.append(str(term))
    return hits


def _plan_text(plan: CartoonEpisodePlan) -> str:
    parts = [
        plan.title,
        plan.topic,
        plan.premise,
        plan.ending_callback or "",
        " ".join(plan.story_tags),
    ]
    for scene in plan.scenes:
        parts.extend(
            [
                scene.setup,
                scene.beat,
                scene.location_id,
                scene.camera,
            ]
        )
        for line in scene.dialogue:
            parts.append(line.text)
    return "\n".join(parts)


def _content_words(plan: CartoonEpisodePlan) -> list[str]:
    # Avoid camera/location boilerplate in text-similarity fingerprints.
    text_parts = [plan.premise, plan.ending_callback or ""]
    for scene in plan.scenes:
        text_parts.append(scene.setup)
        text_parts.extend(line.text for line in scene.dialogue)
    return _norm("\n".join(text_parts)).split()


def _shingle_hashes(plan: CartoonEpisodePlan, size: int = 3) -> list[str]:
    words = _content_words(plan)
    if len(words) < size:
        payload = " ".join(words).encode("utf-8")
        return [hashlib.blake2b(payload, digest_size=8).hexdigest()] if payload else []

    hashes = {
        hashlib.blake2b(
            " ".join(words[i : i + size]).encode("utf-8"),
            digest_size=8,
        ).hexdigest()
        for i in range(len(words) - size + 1)
    }
    return sorted(hashes)


def _structure_signature(plan: CartoonEpisodePlan) -> str:
    payload = {
        "route": plan.route,
        "scene_count": len(plan.scenes),
        "beats": [scene.beat for scene in plan.scenes],
        "locations": [scene.location_id for scene in plan.scenes],
        "ending": bool(plan.ending_callback),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _plan_sha(plan: CartoonEpisodePlan) -> str:
    raw = plan.model_dump_json(exclude_none=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


class StoryFingerprintIndex:
    """
    Persistent history cache.

    Quality impact: none. The exact hashed trigram set is stored for each
    previously rendered episode. Subsequent runs compare against the index
    instead of reparsing every old episode_plan.json.
    """

    def __init__(self, *, project_root: Path) -> None:
        self.project_root = Path(project_root).resolve()
        self.artifacts_root = self.project_root / "artifacts" / "cartoon"
        self.index_dir = self.artifacts_root / ".monetization"
        self.index_path = self.index_dir / "episode_fingerprints.jsonl"
        self.index_dir.mkdir(parents=True, exist_ok=True)

    def _load_records(self) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        if not self.index_path.is_file():
            return records
        for raw in self.index_path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except Exception:
                continue
            if isinstance(item, dict):
                records.append(item)
        return records

    def _write_records(self, records: list[dict[str, object]]) -> None:
        payload = "\n".join(
            json.dumps(item, ensure_ascii=False, sort_keys=True)
            for item in records
        )
        if payload:
            payload += "\n"
        temp = self.index_path.with_suffix(".tmp")
        temp.write_text(payload, encoding="utf-8")
        temp.replace(self.index_path)

    def _record_for_plan(
        self,
        *,
        plan: CartoonEpisodePlan,
        plan_path: Path,
    ) -> dict[str, object]:
        return {
            "plan_path": str(plan_path.resolve()),
            "plan_sha256": _plan_sha(plan),
            "topic": plan.topic,
            "route": plan.route,
            "audience": plan.audience,
            "structure_signature": _structure_signature(plan),
            "shingles": _shingle_hashes(plan),
        }

    def bootstrap(self, *, skip_plan_path: Path | None = None) -> dict[str, int]:
        """
        One-time/backfill scan of rendered runs only.

        Existing indexed paths are not reparsed. This makes future checks scale
        with new episodes rather than total historical episodes.
        """
        start = time.perf_counter()
        records = self._load_records()
        known_paths = {
            str(item.get("plan_path", ""))
            for item in records
        }
        scanned = 0
        added = 0

        if self.artifacts_root.is_dir():
            for plan_path in self.artifacts_root.glob("*/**/story/episode_plan.json"):
                try:
                    resolved = plan_path.resolve()
                    if skip_plan_path is not None and resolved == skip_plan_path.resolve():
                        continue
                    key = str(resolved)
                    if key in known_paths:
                        continue

                    run_root = plan_path.parent.parent
                    run_info_path = run_root / "run_info.json"
                    if not run_info_path.is_file():
                        continue

                    scanned += 1
                    try:
                        info = json.loads(run_info_path.read_text(encoding="utf-8"))
                    except Exception:
                        continue

                    if not bool(info.get("final_video_generated", False)):
                        continue

                    try:
                        plan = CartoonEpisodePlan.model_validate_json(
                            plan_path.read_text(encoding="utf-8")
                        )
                    except Exception:
                        continue

                    records.append(
                        self._record_for_plan(
                            plan=plan,
                            plan_path=plan_path,
                        )
                    )
                    known_paths.add(key)
                    added += 1
                except Exception:
                    continue

        if added:
            self._write_records(records)

        return {
            "existing_records": len(records) - added,
            "scanned_unindexed_runs": scanned,
            "bootstrapped_records": added,
            "total_records": len(records),
            "bootstrap_ms": int((time.perf_counter() - start) * 1000),
        }

    def compare(
        self,
        *,
        plan: CartoonEpisodePlan,
        current_plan_path: Path | None,
    ) -> dict[str, object]:
        start = time.perf_counter()
        records = self._load_records()
        current_shingles = set(_shingle_hashes(plan))
        current_sha = _plan_sha(plan)
        current_structure = _structure_signature(plan)
        current_path = (
            str(current_plan_path.resolve())
            if current_plan_path is not None
            else ""
        )

        max_similarity = 0.0
        closest_topic = None
        closest_path = None
        structure_repeat_count = 0
        candidates = 0

        for record in records:
            record_path = str(record.get("plan_path", ""))
            record_sha = str(record.get("plan_sha256", ""))

            # Re-rendering the same plan is not a new repetitive episode.
            if current_path and record_path == current_path and record_sha == current_sha:
                continue

            candidates += 1

            if str(record.get("structure_signature", "")) == current_structure:
                structure_repeat_count += 1

            old_shingles = {
                str(item)
                for item in record.get("shingles", [])
                if item
            }
            score = _jaccard(current_shingles, old_shingles)
            if score > max_similarity:
                max_similarity = score
                closest_topic = record.get("topic")
                closest_path = record_path

        return {
            "candidates": candidates,
            "max_text_similarity": round(max_similarity, 4),
            "closest_topic": closest_topic,
            "closest_plan": closest_path,
            "same_structure_history_count": structure_repeat_count,
            "compare_ms": int((time.perf_counter() - start) * 1000),
        }

    def register_final(
        self,
        *,
        plan: CartoonEpisodePlan,
        plan_path: Path,
    ) -> bool:
        records = self._load_records()
        new_record = self._record_for_plan(plan=plan, plan_path=plan_path)
        new_path = str(new_record["plan_path"])
        new_sha = str(new_record["plan_sha256"])

        for item in records:
            if (
                str(item.get("plan_path", "")) == new_path
                and str(item.get("plan_sha256", "")) == new_sha
            ):
                return False

        records.append(new_record)
        self._write_records(records)
        return True


def _check(
    *,
    name: str,
    status: str,
    detail: str,
    metric: object | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "name": name,
        "status": status,
        "detail": detail,
    }
    if metric is not None:
        result["metric"] = metric
    return result


def _final_decision(checks: list[dict[str, object]]) -> str:
    statuses = [str(item.get("status", PASS)) for item in checks]
    if BLOCK in statuses:
        return BLOCK
    if REVIEW in statuses:
        return REVIEW
    return PASS


def _upload_ready_from_checks(checks: list[dict[str, object]]) -> bool:
    """V15: upload-ready means no hard automated blocker.

    REVIEW_REQUIRED is advisory: the video may be uploaded after the creator
    reviews the named issue. This avoids the old behavior where every minor
    advisory printed Upload Ready: NO. It is not a monetization guarantee.
    """
    return not any(str(item.get("status", PASS)) == BLOCK for item in checks)


def _blocking_and_review_names(checks: list[dict[str, object]]) -> tuple[list[str], list[str]]:
    blocking = [str(x.get("name", "unknown")) for x in checks if str(x.get("status")) == BLOCK]
    reviews = [str(x.get("name", "unknown")) for x in checks if str(x.get("status")) == REVIEW]
    return blocking, reviews


def _made_for_kids(plan: CartoonEpisodePlan, policy: dict[str, object]) -> tuple[bool | None, str]:
    if plan.audience in set(policy.get("kids_audiences", [])):
        return True, "plan audience explicitly targets kids/family children"
    if plan.audience in set(policy.get("kids_review_audiences", [])):
        return None, "kids/teens mixed audience requires creator review"
    return False, "plan is not explicitly child-directed"


def _ai_disclosure(plan: CartoonEpisodePlan, policy: dict[str, object]) -> tuple[str, list[str]]:
    hits = _contains_any(
        _plan_text(plan),
        policy.get("realistic_ai_review_terms", []),
    )
    if hits:
        return "REVIEW_REALISTIC_SYNTHETIC_DISCLOSURE", hits
    return "NOT_EXPECTED_FOR_STYLIZED_CARTOON", []


def _dialogue_variation_metrics(plan: CartoonEpisodePlan) -> dict[str, object]:
    """Measure exact-line repetition without punishing legitimate comedy callbacks.

    V16.1 deliberately separates *normal intra-episode repetition* (callbacks,
    reactions, names, locally repaired lines) from pathological mass duplication.
    YouTube's repetitive/inauthentic-content concern is primarily a channel-level
    quality signal; exact repetition inside one comedy episode should normally be
    advisory, not an automatic render blocker.
    """
    from collections import Counter

    lines = [
        _norm(line.text)
        for scene in plan.scenes
        for line in scene.dialogue
        if _norm(line.text)
    ]
    total = len(lines)
    if total == 0:
        return {
            "line_count": 0,
            "unique_lines": 0,
            "unique_ratio": 0.0,
            "top_repeat_count": 0,
            "top_repeat_share": 0.0,
            "pathological_duplication": True,
            "reason": "no_dialogue",
        }

    counts = Counter(lines)
    unique = len(counts)
    top_count = max(counts.values())
    top_share = top_count / total
    return {
        "line_count": total,
        "unique_lines": unique,
        "unique_ratio": unique / total,
        "top_repeat_count": top_count,
        "top_repeat_share": top_share,
        "pathological_duplication": False,
        "reason": "ok",
    }


def _dialogue_variation_status(
    plan: CartoonEpisodePlan,
    thresholds: dict[str, object],
) -> tuple[str, dict[str, object]]:
    metrics = _dialogue_variation_metrics(plan)
    total = int(metrics["line_count"])
    if total == 0:
        metrics["pathological_duplication"] = True
        metrics["reason"] = "no_dialogue"
        return BLOCK, metrics

    unique_ratio = float(metrics["unique_ratio"])
    top_count = int(metrics["top_repeat_count"])
    top_share = float(metrics["top_repeat_share"])

    min_lines = int(thresholds.get("internal_dialogue_pathological_block_min_lines", 6))
    block_top_count = int(thresholds.get("internal_dialogue_pathological_block_top_count", 4))
    block_top_share = float(thresholds.get("internal_dialogue_pathological_block_top_share", 0.50))
    review_unique = float(thresholds.get("internal_dialogue_unique_review", 0.62))
    review_top_share = float(thresholds.get("internal_dialogue_top_share_review", 0.30))

    # Hard-block only truly pathological scripts: enough dialogue exists and one
    # exact normalized line dominates the episode. Normal callbacks/reactions are
    # intentionally REVIEW_REQUIRED, not BLOCK_UPLOAD.
    pathological = (
        total >= min_lines
        and top_count >= block_top_count
        and top_share >= block_top_share
    )
    if pathological:
        metrics["pathological_duplication"] = True
        metrics["reason"] = "one_exact_line_dominates_episode"
        return BLOCK, metrics

    if unique_ratio < review_unique or top_share >= review_top_share:
        metrics["reason"] = "repetition_review_recommended"
        return REVIEW, metrics

    return PASS, metrics


def _dialogue_uniqueness(plan: CartoonEpisodePlan) -> float:
    """Backward-compatible helper retained for older tests/callers."""
    return float(_dialogue_variation_metrics(plan)["unique_ratio"])


def _setup_uniqueness(plan: CartoonEpisodePlan) -> float:
    setups = [_norm(scene.setup) for scene in plan.scenes if _norm(scene.setup)]
    if not setups:
        return 0.0
    return len(set(setups)) / len(setups)


def _narrative_check(plan: CartoonEpisodePlan) -> tuple[str, dict[str, object]]:
    beats = [scene.beat for scene in plan.scenes]
    n = len(beats)
    first = beats[: max(1, n // 3)]
    middle = beats[max(1, n // 3) : max(2, (2 * n) // 3)]
    last = beats[max(2, (2 * n) // 3) :]

    has_open = "setup" in first
    has_middle = any(
        beat in {"escalation", "misdirection", "reaction"}
        for beat in middle
    )
    has_end = any(
        beat in {"punchline", "callback", "reaction"}
        for beat in last
    ) or bool(plan.ending_callback)

    status = PASS if has_open and has_middle and has_end else REVIEW
    return status, {
        "opening": has_open,
        "middle": has_middle,
        "ending": has_end,
    }


def run_pre_render_gate(
    *,
    project_root: Path,
    plan: CartoonEpisodePlan,
    plan_path: Path,
) -> GateResult:
    start = time.perf_counter()
    project_root = Path(project_root).resolve()
    policy = _load_policy(project_root)
    thresholds = policy["thresholds"]
    checks: list[dict[str, object]] = []
    text = _plan_text(plan)

    made_for_kids, kids_reason = _made_for_kids(plan, policy)
    ai_disclosure, ai_hits = _ai_disclosure(plan, policy)

    # Original/authentic creation claim.
    originality_note = _norm(plan.originality_note)
    original_claim = (
        "original" in originality_note
        and "copied" in originality_note
    )
    checks.append(
        _check(
            name="originality_provenance_claim",
            status=PASS if original_claim else REVIEW,
            detail=(
                "episode declares original characters/dialogue/assets"
                if original_claim
                else "originality/provenance note is incomplete; manual review needed"
            ),
        )
    )

    # V16.1 internal variation signal. Normal callbacks/reaction repetition are
    # advisory; only pathological exact-line domination hard-blocks rendering.
    dialogue_status, dialogue_metric = _dialogue_variation_status(plan, thresholds)
    checks.append(
        _check(
            name="internal_dialogue_variation",
            status=dialogue_status,
            detail=(
                "exact-line repetition diagnostic; callbacks/reactions are advisory, "
                "pathological duplication only is a hard blocker"
            ),
            metric=dialogue_metric,
        )
    )

    setup_unique = _setup_uniqueness(plan)
    setup_status = (
        REVIEW
        if setup_unique < float(thresholds["internal_setup_unique_review"])
        else PASS
    )
    checks.append(
        _check(
            name="scene_setup_variation",
            status=setup_status,
            detail="unique normalized scene setup ratio",
            metric=round(setup_unique, 4),
        )
    )

    narrative_status, narrative_metric = _narrative_check(plan)
    checks.append(
        _check(
            name="clear_beginning_middle_end",
            status=narrative_status,
            detail="kids/family quality favors a coherent complete narrative",
            metric=narrative_metric,
        )
    )

    # Channel-level cross-episode repetition / inauthentic-content signal.
    index = StoryFingerprintIndex(project_root=project_root)
    bootstrap = index.bootstrap(skip_plan_path=plan_path)
    similarity = index.compare(plan=plan, current_plan_path=plan_path)
    max_similarity = float(similarity["max_text_similarity"])

    if max_similarity >= float(thresholds["cross_episode_similarity_block"]):
        similarity_status = BLOCK
    elif max_similarity >= float(thresholds["cross_episode_similarity_review"]):
        similarity_status = REVIEW
    else:
        similarity_status = PASS

    # Reusing exactly the same broad story structure several times is a
    # secondary review signal, not an automatic block.
    structure_count = int(similarity["same_structure_history_count"])
    if (
        similarity_status == PASS
        and structure_count >= int(thresholds["structure_repeat_review_count"])
    ):
        similarity_status = REVIEW

    checks.append(
        _check(
            name="channel_episode_uniqueness",
            status=similarity_status,
            detail=(
                "compares exact hashed story trigrams + repeated structure "
                "against previously rendered channel episodes"
            ),
            metric=similarity,
        )
    )

    adult_hits = _contains_any(text, policy.get("strong_adult_terms", []))
    shocking_hits = _contains_any(text, policy.get("strong_shocking_terms", []))
    dangerous_hits = _contains_any(text, policy.get("dangerous_kids_terms", []))

    if made_for_kids is True and adult_hits:
        adult_status = BLOCK
    elif adult_hits:
        adult_status = REVIEW
    else:
        adult_status = PASS
    checks.append(
        _check(
            name="adult_mature_theme_scan",
            status=adult_status,
            detail="strong adult/drug/tobacco/alcohol term scan",
            metric={"hits": adult_hits},
        )
    )

    if made_for_kids is True and shocking_hits:
        shocking_status = BLOCK
    elif shocking_hits:
        shocking_status = REVIEW
    else:
        shocking_status = PASS
    checks.append(
        _check(
            name="shocking_graphic_theme_scan",
            status=shocking_status,
            detail="gore/kidnapping/self-harm/graphic-risk term scan",
            metric={"hits": shocking_hits},
        )
    )

    if made_for_kids is True and dangerous_hits:
        dangerous_status = BLOCK
    elif dangerous_hits:
        dangerous_status = REVIEW
    else:
        dangerous_status = PASS
    checks.append(
        _check(
            name="dangerous_kids_behavior_scan",
            status=dangerous_status,
            detail="dangerous imitation/weapon/challenge term scan",
            metric={"hits": dangerous_hits},
        )
    )

    negative_hits = _contains_any(
        text,
        policy.get("negative_behavior_terms", []),
    )
    resolution_hits = _contains_any(
        text,
        policy.get("positive_resolution_terms", []),
    )
    negative_status = PASS
    if made_for_kids is True and negative_hits and not resolution_hits:
        negative_status = REVIEW
    checks.append(
        _check(
            name="negative_behavior_context",
            status=negative_status,
            detail=(
                "negative behavior is not auto-failed when the narrative "
                "clearly resolves it positively"
            ),
            metric={
                "negative_hits": negative_hits,
                "positive_resolution_hits": resolution_hits,
            },
        )
    )

    # Metadata integrity — conservative, no clickbait keyword stuffing.
    title_words = _norm(plan.title).split()
    repeated_title_word = 0
    if title_words:
        repeated_title_word = max(title_words.count(word) for word in set(title_words))
    metadata_status = PASS
    if len(plan.title) > 100 or repeated_title_word >= 4:
        metadata_status = REVIEW
    checks.append(
        _check(
            name="metadata_integrity",
            status=metadata_status,
            detail="title length/repetition sanity check; no keyword stuffing",
            metric={
                "title_chars": len(plan.title),
                "max_repeated_word": repeated_title_word,
            },
        )
    )

    if ai_disclosure.startswith("REVIEW"):
        checks.append(
            _check(
                name="ai_disclosure",
                status=REVIEW,
                detail=(
                    "topic may depict a real person/event; creator must decide "
                    "whether realistic altered/synthetic disclosure is required"
                ),
                metric={"hits": ai_hits},
            )
        )
    else:
        checks.append(
            _check(
                name="ai_disclosure",
                status=PASS,
                detail="stylized fictional cartoon: disclosure not expected by automated check",
                metric={"hits": []},
            )
        )

    decision = _final_decision(checks)
    upload_ready = _upload_ready_from_checks(checks)
    blocking_checks, review_checks = _blocking_and_review_names(checks)
    elapsed = time.perf_counter() - start

    report = {
        "version": "16.1",
        "phase": "pre_render",
        "policy_verified_date": policy["verified_date"],
        "policy_sources": policy["policy_sources"],
        "decision": decision,
        "upload_ready": upload_ready,
        "upload_ready_semantics": "YES means no hard automated blocker; REVIEW_REQUIRED remains advisory and is not a monetization guarantee",
        "blocking_checks": blocking_checks,
        "review_checks": review_checks,
        "made_for_kids": made_for_kids,
        "made_for_kids_reason": kids_reason,
        "ai_disclosure": ai_disclosure,
        "checks": checks,
        "history_index": bootstrap,
        "performance": {
            "gate_seconds": round(elapsed, 4),
            "history_bootstrap_ms": bootstrap["bootstrap_ms"],
            "history_compare_ms": similarity["compare_ms"],
            "llm_calls_added": 0,
            "quality_settings_changed": False,
        },
        "disclaimer": policy["disclaimer"],
    }

    return GateResult(
        decision=decision,
        upload_ready=upload_ready,
        made_for_kids=made_for_kids,
        ai_disclosure=ai_disclosure,
        report=report,
    )


def _wav_quality(path: Path) -> dict[str, object]:
    start = time.perf_counter()
    threshold_dbfs = -45.0
    silent_windows = 0
    total_windows = 0
    clipped_samples = 0
    total_samples = 0
    rms_power_sum = 0.0
    rms_sample_count = 0

    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        rate = wav.getframerate()

        if width != 2:
            return {
                "supported": False,
                "reason": f"expected 16-bit PCM, got sample_width={width}",
                "scan_ms": int((time.perf_counter() - start) * 1000),
            }

        frames_per_window = max(1, int(rate * 0.10))
        peak_limit = 32767.0

        while True:
            raw = wav.readframes(frames_per_window)
            if not raw:
                break

            sample_count = len(raw) // 2
            if sample_count <= 0:
                continue

            total_windows += 1
            sq = 0.0

            for i in range(0, len(raw) - 1, 2):
                value = int.from_bytes(
                    raw[i : i + 2],
                    "little",
                    signed=True,
                )
                abs_value = abs(value)
                if abs_value >= 32760:
                    clipped_samples += 1
                total_samples += 1
                sq += float(value * value)

            rms = math.sqrt(sq / sample_count) if sample_count else 0.0
            if rms <= 0.0:
                dbfs = -120.0
            else:
                dbfs = 20.0 * math.log10(rms / peak_limit)

            if dbfs < threshold_dbfs:
                silent_windows += 1

            rms_power_sum += sq
            rms_sample_count += sample_count

    silence_ratio = (
        silent_windows / total_windows
        if total_windows
        else 1.0
    )
    clipping_ratio = (
        clipped_samples / total_samples
        if total_samples
        else 0.0
    )
    overall_rms = (
        math.sqrt(rms_power_sum / rms_sample_count)
        if rms_sample_count
        else 0.0
    )
    overall_dbfs = (
        20.0 * math.log10(overall_rms / 32767.0)
        if overall_rms > 0.0
        else -120.0
    )

    return {
        "supported": True,
        "channels": channels,
        "sample_rate": rate,
        "silent_ratio": round(silence_ratio, 4),
        "clipping_ratio": round(clipping_ratio, 6),
        "mean_rms_dbfs": round(overall_dbfs, 2),
        "scan_ms": int((time.perf_counter() - start) * 1000),
    }


def run_post_render_gate(
    *,
    project_root: Path,
    plan: CartoonEpisodePlan,
    plan_path: Path,
    render_report_path: Path,
    master_audio_path: Path,
    pre_result: GateResult,
) -> GateResult:
    start = time.perf_counter()
    project_root = Path(project_root).resolve()
    policy = _load_policy(project_root)
    thresholds = policy["thresholds"]
    checks = list(pre_result.report.get("checks", []))

    try:
        render_report = json.loads(
            Path(render_report_path).read_text(encoding="utf-8")
        )
    except Exception as exc:
        render_report = {
            "degraded": True,
            "duration_match": False,
            "voice_engine": "unknown",
            "report_read_error": f"{type(exc).__name__}: {exc}",
        }

    voice_engine = str(render_report.get("voice_engine", "unknown"))
    if voice_engine in {"timed_silence", "timed_silence_fallback", "unknown", "pending", ""}:
        voice_status = BLOCK
    else:
        voice_status = PASS

    checks.append(
        _check(
            name="render_voice_engine",
            status=voice_status,
            detail="silent/unknown TTS is not upload-ready",
            metric={"voice_engine": voice_engine},
        )
    )

    channel_audio_profile = str(render_report.get("channel_audio_profile", ""))
    if plan.language_code in {"hindi", "hinglish", "magahi", "bhojpuri"}:
        # Legacy render reports did not include this field. Missing metadata is
        # tolerated for backward compatibility; V15 renderers always emit it.
        accent_status = PASS if (not channel_audio_profile or "Indian" in channel_audio_profile or "India" in channel_audio_profile) else REVIEW
        checks.append(
            _check(
                name="indian_channel_voice_profile",
                status=accent_status,
                detail="Hindi-mass channel should keep a consistent Indian voice/accent family across episodes",
                metric={"channel_audio_profile": channel_audio_profile or "missing"},
            )
        )

    duration_match = bool(render_report.get("duration_match", False))
    checks.append(
        _check(
            name="audio_video_duration_alignment",
            status=PASS if duration_match else BLOCK,
            detail="delivered MP4 and master WAV must align within renderer tolerance",
            metric={
                "duration_match": duration_match,
                "delta_seconds": render_report.get("duration_delta_seconds"),
            },
        )
    )

    degraded = bool(render_report.get("degraded", False))
    checks.append(
        _check(
            name="renderer_degradation",
            status=REVIEW if degraded else PASS,
            detail="static/emergency fallbacks require human visual review",
            metric={
                "degraded": degraded,
                "warnings": render_report.get("warnings", []),
            },
        )
    )

    wav_metrics = _wav_quality(Path(master_audio_path))
    if not bool(wav_metrics.get("supported", False)):
        audio_status = REVIEW
    else:
        silence_ratio = float(wav_metrics["silent_ratio"])
        clipping_ratio = float(wav_metrics["clipping_ratio"])
        rms_dbfs = float(wav_metrics["mean_rms_dbfs"])

        if (
            silence_ratio >= float(thresholds["silent_ratio_block"])
            or clipping_ratio >= float(thresholds["clipping_ratio_block"])
        ):
            audio_status = BLOCK
        elif (
            silence_ratio >= float(thresholds["silent_ratio_review"])
            or clipping_ratio >= float(thresholds["clipping_ratio_review"])
            or rms_dbfs < float(thresholds["mean_rms_dbfs_review_below"])
        ):
            audio_status = REVIEW
        else:
            audio_status = PASS

    checks.append(
        _check(
            name="audio_clarity_signal",
            status=audio_status,
            detail=(
                "single-pass WAV scan for excessive silence, clipping and "
                "very-low overall level; no extra transcription/LLM"
            ),
            metric=wav_metrics,
        )
    )

    decision = _final_decision(checks)
    upload_ready = _upload_ready_from_checks(checks)
    blocking_checks, review_checks = _blocking_and_review_names(checks)

    # Register any non-blocked final video so future duplicate detection also
    # works when a creator uploaded after an advisory REVIEW_REQUIRED.
    registered = False
    if upload_ready:
        registered = StoryFingerprintIndex(
            project_root=project_root
        ).register_final(
            plan=plan,
            plan_path=plan_path,
        )

    elapsed = time.perf_counter() - start
    report = {
        "version": "15.0",
        "phase": "post_render",
        "policy_verified_date": policy["verified_date"],
        "policy_sources": policy["policy_sources"],
        "decision": decision,
        "upload_ready": upload_ready,
        "upload_ready_semantics": "YES means no hard automated blocker; REVIEW_REQUIRED remains advisory and is not a monetization guarantee",
        "blocking_checks": blocking_checks,
        "review_checks": review_checks,
        "made_for_kids": pre_result.made_for_kids,
        "made_for_kids_reason": pre_result.report.get("made_for_kids_reason"),
        "ai_disclosure": pre_result.ai_disclosure,
        "checks": checks,
        "history_registered_after_pass": registered,
        "performance": {
            "gate_seconds": round(elapsed, 4),
            "audio_scan_ms": wav_metrics.get("scan_ms"),
            "llm_calls_added": 0,
            "quality_settings_changed": False,
        },
        "disclaimer": policy["disclaimer"],
    }

    return GateResult(
        decision=decision,
        upload_ready=upload_ready,
        made_for_kids=pre_result.made_for_kids,
        ai_disclosure=pre_result.ai_disclosure,
        report=report,
    )


def write_gate_report(
    *,
    artifact_root: Path,
    filename: str,
    result: GateResult,
) -> Path:
    compliance = Path(artifact_root) / "compliance"
    compliance.mkdir(parents=True, exist_ok=True)
    path = compliance / filename
    path.write_text(
        json.dumps(result.report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def print_gate_logs(result: GateResult) -> None:
    report = result.report
    phase = report.get("phase", "unknown")
    ready_label = "YES" if result.upload_ready else "NO"
    if result.upload_ready and result.decision == REVIEW:
        ready_label = "YES (REVIEW RECOMMENDED)"
    print(
        f"[MONETIZATION V15] phase={phase}; "
        f"decision={result.decision}; "
        f"upload_ready={ready_label}"
    )
    print(
        f"[MONETIZATION V15] made_for_kids={result.made_for_kids}; "
        f"ai_disclosure={result.ai_disclosure}"
    )

    for item in report.get("checks", []):
        name = item.get("name")
        status = item.get("status")
        if status != PASS:
            metric = item.get("metric")
            suffix = ""
            if isinstance(metric, dict):
                hits = metric.get("hits")
                warnings = metric.get("warnings")
                if hits:
                    suffix += f"; hits={hits}"
                if warnings:
                    suffix += f"; warnings={warnings}"
            print(
                f"[MONETIZATION CHECK] {name}: {status} - "
                f"{item.get('detail', '')}{suffix}"
            )

    blocking = report.get("blocking_checks", [])
    reviews = report.get("review_checks", [])
    if blocking:
        print(f"[MONETIZATION V15] hard_blocks={blocking}")
    elif reviews:
        print(f"[MONETIZATION V15] advisory_reviews={reviews}")
    else:
        print("[MONETIZATION V15] checks=PASS; no hard blockers or advisory reviews")

    perf = report.get("performance", {})
    print(
        "[MONETIZATION PERF] "
        f"gate={float(perf.get('gate_seconds', 0.0)):.3f}s, "
        f"llm_calls_added={int(perf.get('llm_calls_added', 0))}, "
        "quality_settings_changed=NO"
    )
