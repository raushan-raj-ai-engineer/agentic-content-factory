from __future__ import annotations
from content_factory.monetization.readiness import materially_varied as _cf_materially_varied, finalize_monetization_artifacts as _cf_finalize_monetization_artifacts

import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from content_factory.agents.base import Agent
from content_factory.orchestration.state import WorkflowState
from content_factory.utils.artifact_paths import artifact_run_dir


BLOCKED_LICENSE_MARKERS = (
    "non-commercial",
    "noncommercial",
    "cc by-nc",
    "cc-by-nc",
    "by-nc",
    " no commercial",
    "non-free",
    "nonfree",
    "all rights reserved",
)

NO_DERIVATIVES_MARKERS = (
    "cc by-nd",
    "cc-by-nd",
    "by-nd",
    "no derivatives",
    "no-derivatives",
)

PUBLIC_MEDIA_ROUTES = {
    "wikimedia_commons",
}

GENERATED_REALISTIC_TYPES = {
    "real_photo",
    "person_photo",
    "place_photo",
}

POSSIBLY_REALISTIC_TYPES = {
    "photo_illustration",
    "cinematic_explainer",
}


class MonetizationSafetyAgent(Agent):
    """
    Local pre-upload risk gate.

    It does NOT promise YPP approval. It creates a traceable risk report and
    prevents the workflow from marking obviously unsafe assets as upload-ready.
    """

    def __init__(
        self,
        *,
        artifact_root: str = "artifacts",
    ) -> None:
        self._artifact_root = Path(
            artifact_root
        )

    @property
    def name(self) -> str:
        return "Monetization Safety Gate"

    async def execute(
        self,
        state: WorkflowState,
    ) -> WorkflowState:
        run_dir = artifact_run_dir(
            state,
            self._artifact_root,
        )
        output_dir = run_dir / "monetization"
        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        hard_blocks: list[str] = []
        high_risks: list[str] = []
        warnings: list[str] = []
        actions: list[str] = []

        fact_ok = self._check_facts(
            state,
            hard_blocks,
        )

        authenticity = self._authenticity_snapshot(
            state
        )
        authenticity_risk = str(
            authenticity.get("final_risk")
            or authenticity.get(
                "before_risk",
                "LOW",
            )
        )

        if authenticity_risk == "HIGH":
            high_risks.append(
                "Script still looks too reusable/template-like after authenticity review."
            )
        elif authenticity_risk == "MEDIUM":
            warnings.append(
                "Script has some template/repetition signals; review final narration."
            )

        visual_info = self._check_visuals(
            state,
            hard_blocks,
            high_risks,
            warnings,
            actions,
        )

        voice_info = self._check_voice(
            run_dir,
            hard_blocks,
            warnings,
            actions,
        )

        disclosure = self._ai_disclosure(
            state,
            visual_info,
            voice_info,
        )

        if disclosure["decision"] == "YES":
            actions.append(
                "In YouTube Studio > Attributes > AI use, select Yes."
            )
        elif disclosure["decision"] == "REVIEW":
            actions.append(
                "Review whether generated scenes look realistic before choosing "
                "the YouTube AI-use disclosure."
            )

        model_license = self._check_generation_model_license(
            visual_info,
            warnings,
            actions,
        )

        if hard_blocks:
            risk_level = "BLOCKED"
            upload_ready = "NO"
        elif high_risks:
            risk_level = "HIGH"
            upload_ready = "NO"
        elif warnings:
            risk_level = "MEDIUM"
            upload_ready = "REVIEW"
        else:
            risk_level = "LOW"
            upload_ready = "YES"

        report = {
            "generated_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "run_id": state.run_id,
            "topic": state.topic,
            "risk_level": risk_level,
            "upload_ready": upload_ready,
            "fact_check_passed": fact_ok,
            "hard_blocks": hard_blocks,
            "high_risks": high_risks,
            "warnings": warnings,
            "required_actions": self._dedupe(
                actions
            ),
            "authenticity": authenticity,
            "visuals": visual_info,
            "voice": voice_info,
            "ai_disclosure": disclosure,
            "generation_model_license": model_license,
            "note": (
                "This is a local risk-assessment gate, not a guarantee of "
                "YouTube Partner Program approval."
            ),
        }

        report_path = (
            output_dir
            / "monetization_report.json"
        )

        report_path.write_text(
            json.dumps(
                report,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        checklist_path = (
            output_dir
            / "YOUTUBE_UPLOAD_CHECKLIST.md"
        )
        checklist_path.write_text(
            self._checklist(report),
            encoding="utf-8",
        )

        state.metadata[
            "monetization"
        ] = report

        print(
            f"[MONETIZATION] Risk: {risk_level}"
        )
        print(
            f"[MONETIZATION] Upload ready: {upload_ready}"
        )
        print(
            f"[MONETIZATION] AI disclosure: "
            f"{disclosure['decision']}"
        )
        print(
            f"[MONETIZATION] Report: {report_path}"
        )
        print(
            f"[MONETIZATION] Checklist: {checklist_path}"
        )

        for reason in hard_blocks:
            print(
                f"[MONETIZATION] BLOCK: {reason}"
            )

        for reason in high_risks:
            print(
                f"[MONETIZATION] HIGH: {reason}"
            )

        for warning in warnings:
            print(
                f"[MONETIZATION] REVIEW: {warning}"
            )

        # Do not delete generated work. Just prevent unsafe upload-ready status.
        if upload_ready == "NO":
            state.stop_requested = True
            state.status = "monetization_blocked"
        else:
            state.status = (
                "monetization_ready"
                if upload_ready == "YES"
                else "monetization_review_required"
            )

        return state

    @staticmethod
    def _check_facts(
        state: WorkflowState,
        hard_blocks: list[str],
    ) -> bool:
        result = state.fact_check

        if result is None:
            hard_blocks.append(
                "No completed fact-check result is attached to this run."
            )
            return False

        if (
            not result.approved
            or bool(result.issues)
        ):
            hard_blocks.append(
                "Fact checker did not fully approve the final script."
            )
            return False

        return True

    def _check_visuals(
        self,
        state: WorkflowState,
        hard_blocks: list[str],
        high_risks: list[str],
        warnings: list[str],
        actions: list[str],
    ) -> dict[str, Any]:
        if state.visual_generation is None:
            hard_blocks.append(
                "No visual-generation result exists."
            )
            _cf_finalize_monetization_artifacts(state)
            return {
                "scene_count": 0,
                "routes": {},
                "public_media_count": 0,
                "generated_count": 0,
                "quality_records": [],
            }

        artifacts = (
            state.visual_generation.artifacts
        )

        if not artifacts:
            hard_blocks.append(
                "No visual artifacts were generated."
            )
            _cf_finalize_monetization_artifacts(state)
            return {
                "scene_count": 0,
                "routes": {},
                "public_media_count": 0,
                "generated_count": 0,
                "quality_records": [],
            }

        first_path = Path(
            artifacts[0].file_path
        )
        visual_dir = first_path.parent

        quality_path = (
            visual_dir
            / "scene_quality_report.jsonl"
        )

        quality_records: list[
            dict[str, Any]
        ] = []

        if quality_path.exists():
            for line in quality_path.read_text(
                encoding="utf-8"
            ).splitlines():
                try:
                    quality_records.append(
                        json.loads(line)
                    )
                except Exception:
                    continue

        routes = Counter(
            str(
                record.get("route")
                or "unknown"
            )
            for record in quality_records
            if record.get("accepted", True)
        )

        public_media_count = sum(
            count
            for route, count in routes.items()
            if route in PUBLIC_MEDIA_ROUTES
        )

        generated_count = sum(
            count
            for route, count in routes.items()
            if route.startswith("diffusion")
        )

        # License/attribution checks for reusable public assets.
        for artifact in artifacts:
            image_path = Path(
                artifact.file_path
            )
            sidecar = image_path.with_suffix(
                image_path.suffix
                + ".source.json"
            )

            record = next(
                (
                    item
                    for item in quality_records
                    if item.get("file")
                    == image_path.name
                    and item.get(
                        "accepted",
                        True,
                    )
                ),
                None,
            )

            route = (
                str(
                    record.get("route")
                    or ""
                )
                if record
                else ""
            )

            if route not in PUBLIC_MEDIA_ROUTES:
                continue

            if not sidecar.exists():
                hard_blocks.append(
                    f"Public image {image_path.name} has no source/license sidecar."
                )
                continue

            try:
                source = json.loads(
                    sidecar.read_text(
                        encoding="utf-8"
                    )
                )
            except Exception:
                hard_blocks.append(
                    f"Public image {image_path.name} has unreadable license metadata."
                )
                continue

            license_name = str(
                source.get("license")
                or ""
            ).strip()

            normalized = license_name.lower()

            if not license_name:
                hard_blocks.append(
                    f"Public image {image_path.name} has no recorded license."
                )
            elif any(
                marker in normalized
                for marker in BLOCKED_LICENSE_MARKERS
            ):
                hard_blocks.append(
                    f"Public image {image_path.name} uses a non-commercial/"
                    f"non-free license: {license_name}."
                )
            elif any(
                marker in normalized
                for marker in NO_DERIVATIVES_MARKERS
            ):
                hard_blocks.append(
                    f"Public image {image_path.name} uses a no-derivatives "
                    f"license but the pipeline crops/resizes it: {license_name}."
                )

        if public_media_count:
            attribution = (
                visual_dir
                / "ATTRIBUTION.md"
            )
            if not attribution.exists():
                hard_blocks.append(
                    "Reusable public images were used but ATTRIBUTION.md is missing."
                )
            else:
                actions.append(
                    "Keep required public-media attribution from "
                    f"{attribution} with your channel/video records."
                )

        scene_types = []
        if state.production_plan is not None:
            scene_types = [
                scene.visual_type
                for scene in state.production_plan.visual_scenes
            ]

        scene_type_counts = Counter(
            scene_types
        )

        if (
            (len(scene_types) >= 8
            and len(scene_type_counts) <= 1) and not _cf_materially_varied(state)
        ):
            high_risks.append(
                "Nearly the entire video uses one visual treatment, creating a "
                "template/slideshow feel."
            )
        elif (
            len(scene_types) >= 8
            and len(scene_type_counts) <= 2
        ):
            warnings.append(
                "Visual variety is low for a long video; review viewer-friendliness."
            )

        if quality_records:
            fallback_count = sum(
                1
                for record in quality_records
                if record.get("accepted", True)
                and str(
                    record.get("route")
                    or ""
                ) in {
                    "crisp_fallback",
                    "news_editorial_fallback",
                }
            )

            if fallback_count / max(
                1,
                len(artifacts),
            ) >= 0.50:
                warnings.append(
                    "At least half of scenes used generic visual fallbacks."
                )

        _cf_finalize_monetization_artifacts(state)
        return {
            "scene_count": len(artifacts),
            "scene_type_counts": dict(
                scene_type_counts
            ),
            "routes": dict(routes),
            "public_media_count": public_media_count,
            "generated_count": generated_count,
            "quality_records": quality_records,
            "visual_dir": str(visual_dir),
        }

    @staticmethod
    def _check_voice(
        run_dir: Path,
        hard_blocks: list[str],
        warnings: list[str],
        actions: list[str],
    ) -> dict[str, Any]:
        manifest_path = (
            run_dir
            / "audio"
            / "voice_manifest.json"
        )

        if not manifest_path.exists():
            warnings.append(
                "voice_manifest.json is missing; voice identity/license cannot "
                "be fully audited."
            )
            return {
                "manifest_found": False,
                "entries": [],
                "clone_detected": False,
            }

        try:
            entries = json.loads(
                manifest_path.read_text(
                    encoding="utf-8"
                )
            )
        except Exception:
            warnings.append(
                "voice_manifest.json is unreadable."
            )
            return {
                "manifest_found": False,
                "entries": [],
                "clone_detected": False,
            }

        clone_entries = [
            item
            for item in entries
            if any(
                token in str(
                    item.get("backend")
                    or ""
                ).lower()
                for token in (
                    "clone",
                    "openvoice",
                )
            )
        ]

        if clone_entries:
            owner = os.getenv(
                "CONTENT_FACTORY_VOICE_CLONE_OWNER",
                "",
            ).strip().lower()

            if owner in {
                "self",
                "own",
                "me",
                "user",
            }:
                actions.append(
                    "Voice clone is marked as the creator's own voice; keep "
                    "proof/consent records."
                )
            else:
                hard_blocks.append(
                    "A cloned voice is present but "
                    "CONTENT_FACTORY_VOICE_CLONE_OWNER is not explicitly set "
                    "to self/own. Do not upload until voice identity/consent is clear."
                )

        piper_voices = sorted(
            {
                str(
                    item.get("voice")
                    or ""
                )
                for item in entries
                if str(
                    item.get("backend")
                    or ""
                ).lower() == "piper"
                and item.get("voice")
            }
        )

        if piper_voices:
            actions.append(
                "Review the MODEL_CARD/license for every Piper voice used: "
                + ", ".join(
                    piper_voices
                )
                + "."
            )

        return {
            "manifest_found": True,
            "entries": entries,
            "clone_detected": bool(
                clone_entries
            ),
            "piper_voices": piper_voices,
        }

    @staticmethod
    def _ai_disclosure(
        state: WorkflowState,
        visual_info: dict[str, Any],
        voice_info: dict[str, Any],
    ) -> dict[str, Any]:
        reasons: list[str] = []
        decision = "NO"

        quality_records = visual_info.get(
            "quality_records",
            []
        )

        route_by_file = {
            str(
                item.get("file")
                or ""
            ): str(
                item.get("route")
                or ""
            )
            for item in quality_records
            if item.get("accepted", True)
        }

        if (
            state.visual_generation is not None
            and state.production_plan is not None
        ):
            scene_by_id = {
                scene.id: scene
                for scene in state.production_plan.visual_scenes
            }

            for artifact in state.visual_generation.artifacts:
                scene = scene_by_id.get(
                    artifact.scene_id
                )

                if scene is None:
                    continue

                route = route_by_file.get(
                    Path(
                        artifact.file_path
                    ).name,
                    "",
                )

                generated = route.startswith(
                    "diffusion"
                )

                if (
                    generated
                    and scene.visual_type
                    in GENERATED_REALISTIC_TYPES
                ):
                    decision = "YES"
                    reasons.append(
                        f"Generated realistic real-world scene: "
                        f"{scene.title} ({scene.visual_type})."
                    )

                elif (
                    generated
                    and scene.visual_type
                    in POSSIBLY_REALISTIC_TYPES
                    and decision != "YES"
                ):
                    decision = "REVIEW"
                    reasons.append(
                        f"Generated scene may look realistic: "
                        f"{scene.title} ({scene.visual_type})."
                    )

        if voice_info.get(
            "clone_detected"
        ):
            owner = os.getenv(
                "CONTENT_FACTORY_VOICE_CLONE_OWNER",
                "",
            ).strip().lower()

            if owner not in {
                "self",
                "own",
                "me",
                "user",
            }:
                decision = "YES"
                reasons.append(
                    "A voice clone not explicitly marked as the creator's own voice "
                    "requires disclosure/consent review."
                )

        return {
            "decision": decision,
            "reasons": reasons,
        }

    @staticmethod
    def _check_generation_model_license(
        visual_info: dict[str, Any],
        warnings: list[str],
        actions: list[str],
    ) -> dict[str, Any]:
        generated_count = int(
            visual_info.get(
                "generated_count",
                0,
            )
        )

        if generated_count <= 0:
            return {
                "model": None,
                "used": False,
                "review_required": False,
            }

        acknowledged = os.getenv(
            "CONTENT_FACTORY_STABILITY_LICENSE_REVIEWED",
            "",
        ).strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
        }

        if not acknowledged:
            warnings.append(
                "SD-Turbo-generated visuals are present and the Stability AI "
                "commercial/community license has not been marked reviewed."
            )
            actions.append(
                "Review the current Stability AI license for SD-Turbo and, "
                "after confirming it applies to your use, set "
                "CONTENT_FACTORY_STABILITY_LICENSE_REVIEWED=1."
            )

        return {
            "model": "stabilityai/sd-turbo",
            "used": True,
            "generated_scene_count": generated_count,
            "review_required": not acknowledged,
        }

    @staticmethod
    def _authenticity_snapshot(
        state: WorkflowState,
    ) -> dict[str, Any]:
        review = dict(
            state.metadata.get(
                "authenticity_review",
                {}
            )
        )

        if state.script is None:
            return review

        narration = " ".join(
            [
                state.script.hook,
                state.script.introduction,
                *(
                    section.content
                    for section in state.script.sections
                ),
                state.script.conclusion,
                state.script.call_to_action,
            ]
        )

        stop_words = {
            "the", "a", "an", "and", "or", "to", "of", "in",
            "on", "for", "with", "this", "that", "is", "are",
            "was", "were", "it", "its", "we", "you", "your",
            "our", "from", "as", "at", "by", "today", "video",
        }

        counts: Counter[str] = Counter(
            token.lower()
            for token in re.findall(
                r"[A-Za-zÀ-ÿ\u0900-\u097F\u0400-\u04FF]{3,}",
                narration,
            )
            if token.lower()
            not in stop_words
        )

        review[
            "signature_tokens"
        ] = [
            word
            for word, _
            in counts.most_common(
                180
            )
        ]

        review[
            "section_titles"
        ] = [
            section.title
            for section in state.script.sections
        ]

        return review

    @staticmethod
    def _dedupe(
        values: list[str],
    ) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()

        for value in values:
            key = value.strip().lower()
            if key and key not in seen:
                seen.add(key)
                result.append(
                    value.strip()
                )

        return result

    @staticmethod
    def _checklist(
        report: dict[str, Any],
    ) -> str:
        actions = report.get(
            "required_actions",
            [],
        )
        blocks = report.get(
            "hard_blocks",
            [],
        )
        warnings = report.get(
            "warnings",
            [],
        )

        lines = [
            "# YouTube Upload Checklist",
            "",
            f"- Topic: **{report.get('topic') or 'unknown'}**",
            f"- Monetization risk: **{report.get('risk_level')}**",
            f"- Upload ready: **{report.get('upload_ready')}**",
            f"- AI use disclosure: **{report.get('ai_disclosure', {}).get('decision')}**",
            f"- Fact check passed: **{report.get('fact_check_passed')}**",
            "",
            "## Before upload",
        ]

        if actions:
            lines.extend(
                f"- [ ] {item}"
                for item in actions
            )
        else:
            lines.append(
                "- [x] No additional automated actions detected."
            )

        if blocks:
            lines.extend(
                [
                    "",
                    "## Blocking issues",
                    *(
                        f"- ❌ {item}"
                        for item in blocks
                    ),
                ]
            )

        if warnings:
            lines.extend(
                [
                    "",
                    "## Review items",
                    *(
                        f"- ⚠️ {item}"
                        for item in warnings
                    ),
                ]
            )

        lines.extend(
            [
                "",
                "## Reminder",
                "",
                (
                    "This checklist is a local risk assessment. YouTube reviews "
                    "channels/videos under its current monetization, reused-content, "
                    "inauthentic-content, copyright, advertiser-friendly, and "
                    "synthetic-content rules."
                ),
                "",
            ]
        )

        return "\n".join(
            lines
        )
