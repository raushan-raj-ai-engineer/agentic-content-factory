from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from content_factory.agents.base import Agent
from content_factory.orchestration.state import WorkflowState
from content_factory.utils.artifact_paths import artifact_run_dir


class GrowthReadinessAgent(Agent):
    """
    Heuristic pre-upload growth audit.

    This is NOT a virality prediction. It scores controllable packaging,
    opening, pacing and satisfaction signals so weak areas are visible.
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
        return "Growth Readiness Agent"

    async def execute(
        self,
        state: WorkflowState,
    ) -> WorkflowState:
        if state.script is None:
            raise ValueError(
                "Script is required for growth readiness."
            )

        packaging = state.metadata.get(
            "packaging",
            {},
        )
        growth_plan = state.metadata.get(
            "growth_plan",
            {},
        )

        appeal, appeal_notes = self._appeal(
            state,
            packaging,
        )
        engagement, engagement_notes = self._engagement(
            state,
        )
        satisfaction, satisfaction_notes = self._satisfaction(
            state,
        )

        overall = round(
            appeal * 0.35
            + engagement * 0.40
            + satisfaction * 0.25
        )

        if overall >= 85:
            label = "STRONG"
        elif overall >= 70:
            label = "GOOD"
        elif overall >= 55:
            label = "REVIEW"
        else:
            label = "WEAK"

        run_dir = artifact_run_dir(
            state,
            self._artifact_root,
        )
        growth_dir = run_dir / "growth"
        growth_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        report = {
            "topic": state.topic,
            "overall_score": overall,
            "label": label,
            "appeal": {
                "score": appeal,
                "notes": appeal_notes,
            },
            "engagement": {
                "score": engagement,
                "notes": engagement_notes,
            },
            "satisfaction": {
                "score": satisfaction,
                "notes": satisfaction_notes,
            },
            "packaging": packaging,
            "growth_plan": growth_plan,
            "note": (
                "This is a local readiness heuristic, not a guarantee of views, "
                "virality, recommendations or monetization."
            ),
        }

        report_path = (
            growth_dir
            / "growth_readiness_report.json"
        )
        report_path.write_text(
            json.dumps(
                report,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        ab_path = (
            growth_dir
            / "YOUTUBE_AB_TEST_PLAN.md"
        )
        ab_path.write_text(
            self._ab_plan(
                state,
                packaging,
            ),
            encoding="utf-8",
        )

        short_path = (
            growth_dir
            / "SHORTS_REPURPOSE_PLAN.md"
        )
        short_path.write_text(
            self._shorts_plan(
                growth_plan,
            ),
            encoding="utf-8",
        )

        state.metadata[
            "growth_readiness"
        ] = report

        print(
            f"[GROWTH] Readiness: {overall}/100 ({label})"
        )
        print(
            f"[GROWTH] Appeal={appeal}, "
            f"Engagement={engagement}, "
            f"Satisfaction={satisfaction}"
        )
        print(
            f"[GROWTH] Report: {report_path}"
        )
        print(
            f"[GROWTH] A/B plan: {ab_path}"
        )

        state.status = "growth_reviewed"
        return state

    @staticmethod
    def _appeal(
        state: WorkflowState,
        packaging: dict[str, Any],
    ) -> tuple[int, list[str]]:
        score = 45
        notes: list[str] = []

        variants = packaging.get(
            "variants",
            [],
        )

        if len(variants) == 3:
            score += 20
            notes.append(
                "Three title/thumbnail packages available for testing."
            )
        else:
            notes.append(
                "Fewer than three packaging variants are available."
            )

        title = state.script.title.strip()

        if 35 <= len(title) <= 75:
            score += 15
            notes.append(
                "Default title length is concise."
            )
        elif len(title) <= 90:
            score += 8
        else:
            notes.append(
                "Default title is long and may truncate."
            )

        clickbait_markers = (
            "you won't believe",
            "shocking!!!",
            "must watch!!!",
            "100% guaranteed",
            "secret they don't want",
        )

        if any(
            marker in title.lower()
            for marker in clickbait_markers
        ):
            score -= 25
            notes.append(
                "Default title contains clickbait-style wording."
            )
        else:
            score += 10

        if variants:
            texts = [
                str(
                    item.get(
                        "thumbnail_text",
                        ""
                    )
                ).split()
                for item in variants
            ]
            if all(
                len(words) <= 4
                for words in texts
            ):
                score += 10
                notes.append(
                    "Thumbnail overlay text is mobile-friendly."
                )

        return max(
            0,
            min(score, 100),
        ), notes

    @staticmethod
    def _engagement(
        state: WorkflowState,
    ) -> tuple[int, list[str]]:
        script = state.script

        hook_words = len(
            re.findall(
                r"\b[\w@./+-]+\b",
                script.hook,
                flags=re.UNICODE,
            )
        )

        intro_words = len(
            re.findall(
                r"\b[\w@./+-]+\b",
                script.introduction,
                flags=re.UNICODE,
            )
        )

        opening = (
            script.hook
            + " "
            + script.introduction
        ).lower()

        score = 35
        notes: list[str] = []

        if hook_words <= 22:
            score += 20
            notes.append(
                "Hook is concise."
            )
        elif hook_words <= 35:
            score += 10
        else:
            notes.append(
                "Hook is longer than ideal for a fast opening."
            )

        if intro_words <= 80:
            score += 20
            notes.append(
                "Intro is compact enough for the first ~30 seconds."
            )
        elif intro_words <= 120:
            score += 10
        else:
            notes.append(
                "Intro is long and may delay payoff."
            )

        generic = (
            "welcome back",
            "welcome to",
            "in today's video",
            "before we begin",
        )

        if not any(
            phrase in opening
            for phrase in generic
        ):
            score += 15
            notes.append(
                "Opening avoids generic channel-intro filler."
            )
        else:
            notes.append(
                "Opening contains generic intro language."
            )

        scene_types = []
        if state.production_plan is not None:
            scene_types = [
                scene.visual_type
                for scene in state.production_plan.visual_scenes
            ]

        if len(scene_types) >= 8:
            diversity = len(
                set(scene_types)
            )

            if diversity >= 4:
                score += 10
                notes.append(
                    "Visual treatment is varied."
                )
            elif diversity <= 2:
                score -= 10
                notes.append(
                    "Visual variety is low for a long video."
                )

        return max(
            0,
            min(score, 100),
        ), notes

    @staticmethod
    def _satisfaction(
        state: WorkflowState,
    ) -> tuple[int, list[str]]:
        score = 45
        notes: list[str] = []

        fact = state.fact_check

        if (
            fact is not None
            and fact.approved
            and not fact.issues
        ):
            score += 30
            notes.append(
                "Final script passed factual review."
            )
        else:
            notes.append(
                "Final factual approval is incomplete."
            )

        authenticity = state.metadata.get(
            "authenticity_review",
            {},
        )

        risk = (
            authenticity.get(
                "final_risk"
            )
            or authenticity.get(
                "before_risk"
            )
            or "LOW"
        )

        if risk == "LOW":
            score += 15
            notes.append(
                "Low template/repetition risk."
            )
        elif risk == "MEDIUM":
            score += 5
            notes.append(
                "Some template/repetition signals remain."
            )
        else:
            score -= 15
            notes.append(
                "High template/repetition risk."
            )

        cta_words = len(
            re.findall(
                r"\b[\w@./+-]+\b",
                state.script.call_to_action,
                flags=re.UNICODE,
            )
        )

        if cta_words <= 50:
            score += 10
            notes.append(
                "CTA is concise."
            )

        return max(
            0,
            min(score, 100),
        ), notes

    @staticmethod
    def _ab_plan(
        state: WorkflowState,
        packaging: dict[str, Any],
    ) -> str:
        variants = packaging.get(
            "variants",
            [],
        )

        lines = [
            "# YouTube Title + Thumbnail A/B Test Plan",
            "",
            f"Topic: **{state.topic or 'unknown'}**",
            "",
            (
                "Use YouTube Studio's native A/B testing for long-form videos "
                "when your channel has access. Test materially different "
                "packages and judge the result by YouTube's watch-time-based "
                "winner, not CTR alone."
            ),
            "",
        ]

        for index, item in enumerate(
            variants,
            start=1,
        ):
            letter = chr(
                ord("A") + index - 1
            )
            lines.extend(
                [
                    f"## Variant {letter}",
                    "",
                    f"**Title:** {item.get('title', '')}",
                    "",
                    f"**Thumbnail text:** {item.get('thumbnail_text', '') or '(no text)'}",
                    "",
                    f"**Angle:** {item.get('angle', '')}",
                    "",
                    f"**Thumbnail file:** `thumbnail_{letter}.png`",
                    "",
                ]
            )

        lines.extend(
            [
                "## What to review after publishing",
                "",
                "- Home + Suggested impressions and CTR in context",
                "- first 30-second retention",
                "- average view duration / retention curve",
                "- spikes and dips",
                "- comments / satisfaction signals",
                "- returning viewers over time",
                "",
            ]
        )

        return "\n".join(
            lines
        )

    @staticmethod
    def _shorts_plan(
        growth_plan: dict[str, Any],
    ) -> str:
        angles = growth_plan.get(
            "short_clip_angles",
            [],
        )

        lines = [
            "# Shorts Repurpose Plan",
            "",
            (
                "These are clip concepts from the long-form topic. "
                "They are not automatically uploaded."
            ),
            "",
        ]

        if not angles:
            lines.append(
                "- No short-form clip angles were generated."
            )
        else:
            for index, angle in enumerate(
                angles,
                start=1,
            ):
                lines.append(
                    f"{index}. {angle}"
                )

        lines.extend(
            [
                "",
                "Each Short should stand alone, deliver value quickly, and point "
                "interested viewers toward the full long-form video without "
                "misleading them.",
                "",
            ]
        )

        return "\n".join(
            lines
        )
