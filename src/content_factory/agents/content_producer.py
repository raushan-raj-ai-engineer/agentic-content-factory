from __future__ import annotations
from content_factory.monetization.readiness import prepare_plan_for_monetization as _cf_prepare_plan

import math
import re
from collections import Counter
from typing import Any

from content_factory.agents.base import Agent
from content_factory.llm.base import LLMProvider
from content_factory.models.content import (
    ContentProductionPlan,
    VisualScene,
    VoiceSegment,
)
from content_factory.orchestration.state import WorkflowState
from content_factory.visual.domain_registry import (
    classify_domain,
    domain_family,
)
from content_factory.utils.unicode_tokens import unicode_tokens


STOP_WORDS = {
    "the", "and", "that", "this", "with", "from", "into", "about", "have",
    "will", "would", "could", "should", "there", "their", "they", "them",
    "what", "when", "where", "which", "while", "your", "you", "our", "for",
    "are", "was", "were", "been", "being", "has", "had", "its", "not", "but",
    "can", "may", "might", "than", "then", "also", "just", "more", "most",
    "some", "such", "only", "over", "under", "after", "before", "between",
    "through", "today", "video", "viewer", "viewers", "scene",
}


class ContentProductionAgent(Agent):
    """
    Build a production plan directly from the approved script.

    The script has already gone through writing/review/fact-check stages, so
    asking the LLM to regenerate a huge paired voice/visual JSON plan adds
    latency and can weaken semantic alignment. V3 pairs each narration chunk
    with exactly one domain-aware visual scene deterministically.

    Constructor keeps `llm` for backward compatibility with main.py.
    """

    def __init__(
        self,
        llm: LLMProvider | None = None,
    ) -> None:
        self._llm = llm

    @property
    def name(self) -> str:
        return "Content Production Agent"

    async def execute(
        self,
        state: WorkflowState,
    ) -> WorkflowState:
        if state.script is None:
            raise ValueError(
                "YouTube script is required."
            )

        if not state.script_approved:
            raise ValueError(
                "Script must be approved before production."
            )

        script = state.script
        topic = (
            state.topic
            or script.title
        )

        strategy_context = ""

        if state.strategy is not None:
            strategy_context = " ".join(
                [
                    str(
                        state.strategy.content_type
                        or ""
                    ),
                    str(
                        state.strategy.angle
                        or ""
                    ),
                ]
            )

        grounding_keywords = " ".join(
            str(
                item
            )
            for item in state.metadata.get(
                "topic_grounding",
                {},
            ).get(
                "top_keywords",
                [],
            )[:12]
        )

        context = " ".join(
            [
                topic,
                script.title,
                script.hook,
                script.introduction,
                " ".join(
                    section.title
                    for section in script.sections
                ),
                strategy_context,
                grounding_keywords,
            ]
        )

        identity_context = " ".join(
            [
                topic,
                script.title,
                (
                    str(
                        state.strategy.content_type
                        or ""
                    )
                    if state.strategy is not None
                    else ""
                ),
                (
                    str(
                        state.strategy.angle
                        or ""
                    )
                    if state.strategy is not None
                    else ""
                ),
            ]
        )

        classification = self._resolve_domain_classification(
            identity_context=identity_context,
            full_context=context,
            has_factual_evidence=bool(
                state.research is not None
                or state.metadata.get(
                    "enriched_evidence"
                )
            ),
        )

        domain = classification.domain
        family = classification.family

        state.metadata[
            "domain_classification"
        ] = classification.to_dict()

        print(
            "[DOMAIN] "
            f"{classification.domain} "
            f"family={classification.family} "
            f"score={classification.score:.1f} "
            f"confidence={classification.confidence:.2f} "
            f"secondary={classification.secondary_domain}:"
            f"{classification.secondary_score:.1f} "
            f"ambiguous={classification.ambiguous}"
        )

        growth_plan = state.metadata.get(
            "growth_plan",
            {},
        )

        interval = int(
            growth_plan.get(
                "pattern_interrupt_interval_seconds",
                32,
            )
            or 32
        )
        interval = max(
            22,
            min(
                42,
                interval,
            ),
        )

        wpm = self._words_per_minute(
            state
        )

        target_words = round(
            wpm
            * interval
            / 60.0
        )

        if domain in {
            "cartoon",
            "gaming",
        }:
            # Creative frames are more expensive, so retain each high-quality
            # illustration a little longer while staying inside growth pacing.
            target_words = max(
                58,
                min(
                    82,
                    target_words,
                ),
            )
        else:
            target_words = max(
                42,
                min(
                    68,
                    target_words,
                ),
            )

        blocks = self._script_blocks(
            script,
            language_code=str(
                state.metadata.get(
                    "target_language",
                    "en",
                )
                or "en"
            ),
        )

        voice_segments: list[
            VoiceSegment
        ] = []
        visual_scenes: list[
            VisualScene
        ] = []

        scene_id = 1
        recent_types: list[str] = []

        for block_index, (
            section_name,
            text,
            block_kind,
        ) in enumerate(
            blocks,
            start=1,
        ):
            chunks = self._split_text(
                text,
                target_words=target_words,
            )

            for chunk_index, chunk in enumerate(
                chunks,
                start=1,
            ):
                duration = self._duration_seconds(
                    chunk,
                    wpm,
                )

                voice_segments.append(
                    VoiceSegment(
                        id=scene_id,
                        text=chunk,
                        estimated_duration_seconds=duration,
                    )
                )

                visual_type = self._visual_type(
                    domain=domain,
                    family=family,
                    topic=topic,
                    title=section_name,
                    text=chunk,
                    block_kind=block_kind,
                    scene_index=scene_id,
                    recent_types=recent_types,
                )

                recent_types.append(
                    visual_type
                )
                recent_types = recent_types[
                    -2:
                ]

                elements = self._key_elements(
                    topic=topic,
                    section_name=section_name,
                    text=chunk,
                    domain=domain,
                )

                scene_title = self._scene_title(
                    topic=topic,
                    section_name=section_name,
                    chunk_index=chunk_index,
                    chunk_count=len(
                        chunks
                    ),
                    block_kind=block_kind,
                )

                visual_scenes.append(
                    VisualScene(
                        id=scene_id,
                        title=scene_title,
                        description=chunk,
                        visual_type=visual_type,
                        subject=self._subject(
                            topic=topic,
                            section_name=section_name,
                            elements=elements,
                        ),
                        key_elements=elements,
                        composition=self._composition(
                            visual_type=visual_type,
                            domain=domain,
                        ),
                        style=self._style(
                            visual_type=visual_type,
                            domain=domain,
                        ),
                        avoid=self._avoid(
                            domain=domain,
                            visual_type=visual_type,
                        ),
                        voice_segment_id=scene_id,
                    )
                )

                scene_id += 1

        self._ensure_upload_ready_visual_variety(
            visual_scenes=visual_scenes,
            domain=domain,
            family=family,
        )

        if len(
            voice_segments
        ) != len(
            visual_scenes
        ):
            raise RuntimeError(
                "Production pairing invariant failed."
            )

        packaging = state.metadata.get(
            "packaging",
            {},
        )

        description_opening = str(
            packaging.get(
                "description_opening",
                ""
            )
            or ""
        ).strip()

        youtube_description = self._youtube_description(
            description_opening=description_opening,
            script=script,
        )

        youtube_tags = self._youtube_tags(
            topic=topic,
            script_title=script.title,
            domain=domain,
        )

        plan = ContentProductionPlan(
            title=script.title,
            voice_segments=voice_segments,
            visual_scenes=visual_scenes,
            thumbnail_prompt=self._thumbnail_prompt(
                topic=topic,
                title=script.title,
                domain=domain,
            ),
            youtube_description=youtube_description,
            youtube_tags=youtube_tags,
        )

        state.production_plan = plan
        state.production_plan = _cf_prepare_plan(state.production_plan, state)
        state.metadata[
            "production_domain"
        ] = domain
        state.metadata[
            "production_planner"
        ] = {
            "mode": "deterministic_semantic_v3",
            "domain": domain,
            "scene_count": len(
                visual_scenes
            ),
            "target_words_per_scene": target_words,
            "target_visual_interval_seconds": interval,
            "estimated_wpm": wpm,
        }
        state.status = "production_planned"

        print(
            "[PRODUCTION] Deterministic semantic planner: "
            f"domain={domain}, "
            f"scenes={len(visual_scenes)}, "
            f"target≈{target_words} words/scene"
        )

        return state

    @staticmethod
    def _resolve_domain_classification(
        *,
        identity_context: str,
        full_context: str,
        has_factual_evidence: bool,
    ):
        """
        Prevent a single body section from hijacking the entire video domain.

        Example:
          Topic: "21 De Agosto"
          One section mentions LPL/LCK games
          Full-context classifier -> gaming/creative

        The topic/title identity itself is not gaming, so current factual
        evidence should stay general/editorial instead of generating nine
        expensive game-art frames.
        """
        identity = classify_domain(
            identity_context,
            "",
        )

        full = classify_domain(
            full_context,
            "",
        )

        if (
            has_factual_evidence
            and full.family == "creative"
            and identity.family != "creative"
        ):
            print(
                "[DOMAIN GUARD] Ignoring body-only creative signal: "
                f"full={full.domain}/{full.family}, "
                f"identity={identity.domain}/{identity.family}"
            )

            if identity.domain != "general":
                return identity

            return classify_domain(
                "",
                "",
            )

        return full

    @staticmethod
    def _script_blocks(
        script: Any,
        *,
        language_code: str = "en",
    ) -> list[
        tuple[
            str,
            str,
            str,
        ]
    ]:
        labels = {
            "en": {
                "context": "Context",
                "meaning": "What It Means",
                "next": "What to Watch Next",
            },
            "hi": {
                "context": "संदर्भ",
                "meaning": "इसका मतलब क्या है",
                "next": "आगे क्या देखें",
            },
            "es": {
                "context": "Contexto",
                "meaning": "Qué significa",
                "next": "Qué seguir ahora",
            },
            "pt": {
                "context": "Contexto",
                "meaning": "O que isso significa",
                "next": "O que acompanhar agora",
            },
            "id": {
                "context": "Konteks",
                "meaning": "Artinya",
                "next": "Yang perlu dipantau",
            },
            "ja": {
                "context": "背景",
                "meaning": "その意味",
                "next": "次に注目すること",
            },
            "ar": {
                "context": "السياق",
                "meaning": "ماذا يعني ذلك",
                "next": "ما الذي نتابعه لاحقاً",
            },
            "bn": {
                "context": "প্রেক্ষাপট",
                "meaning": "এর অর্থ কী",
                "next": "এরপর কী দেখবেন",
            },
            "fr": {
                "context": "Contexte",
                "meaning": "Ce que cela signifie",
                "next": "À suivre",
            },
            "ur": {
                "context": "پس منظر",
                "meaning": "اس کا کیا مطلب ہے",
                "next": "آگے کیا دیکھیں",
            },
        }

        selected = labels.get(
            language_code.strip().lower(),
            labels["en"],
        )

        blocks: list[
            tuple[
                str,
                str,
                str,
            ]
        ] = []

        if script.hook.strip():
            blocks.append(
                (
                    script.title,
                    script.hook.strip(),
                    "hook",
                )
            )

        if script.introduction.strip():
            blocks.append(
                (
                    selected[
                        "context"
                    ],
                    script.introduction.strip(),
                    "introduction",
                )
            )

        for section in script.sections:
            if section.content.strip():
                blocks.append(
                    (
                        section.title.strip()
                        or "Main Point",
                        section.content.strip(),
                        "section",
                    )
                )

        if script.conclusion.strip():
            blocks.append(
                (
                    selected[
                        "meaning"
                    ],
                    script.conclusion.strip(),
                    "conclusion",
                )
            )

        if script.call_to_action.strip():
            blocks.append(
                (
                    selected[
                        "next"
                    ],
                    script.call_to_action.strip(),
                    "cta",
                )
            )

        return blocks

    @classmethod
    def _split_text(
        cls,
        text: str,
        *,
        target_words: int,
    ) -> list[str]:
        clean = re.sub(
            r"\s+",
            " ",
            text,
        ).strip()

        if not clean:
            return []

        sentences = re.split(
            r"(?<=[.!?।])\s+",
            clean,
        )

        sentences = [
            item.strip()
            for item in sentences
            if item.strip()
        ]

        if not sentences:
            return [
                clean
            ]

        max_words = max(
            target_words + 18,
            round(
                target_words
                * 1.30
            ),
        )
        min_words = max(
            18,
            round(
                target_words
                * 0.55
            ),
        )

        chunks: list[str] = []
        current: list[str] = []
        current_words = 0

        for sentence in sentences:
            sentence_words = cls._word_count(
                sentence
            )

            if (
                current
                and current_words
                + sentence_words
                > max_words
                and current_words
                >= min_words
            ):
                chunks.append(
                    " ".join(
                        current
                    )
                )
                current = []
                current_words = 0

            if sentence_words > max_words:
                if current:
                    chunks.append(
                        " ".join(
                            current
                        )
                    )
                    current = []
                    current_words = 0

                chunks.extend(
                    cls._split_long_sentence(
                        sentence,
                        max_words=max_words,
                    )
                )
                continue

            current.append(
                sentence
            )
            current_words += sentence_words

            if current_words >= target_words:
                chunks.append(
                    " ".join(
                        current
                    )
                )
                current = []
                current_words = 0

        if current:
            tail = " ".join(
                current
            )

            # Avoid a tiny final chunk where possible.
            if (
                chunks
                and cls._word_count(
                    tail
                )
                < min_words
            ):
                merged = (
                    chunks[-1]
                    + " "
                    + tail
                )

                if cls._word_count(
                    merged
                ) <= (
                    max_words
                    + 12
                ):
                    chunks[-1] = merged
                else:
                    chunks.append(
                        tail
                    )
            else:
                chunks.append(
                    tail
                )

        return chunks

    @classmethod
    def _split_long_sentence(
        cls,
        text: str,
        *,
        max_words: int,
    ) -> list[str]:
        words = text.split()

        return [
            " ".join(
                words[
                    index:
                    index + max_words
                ]
            )
            for index in range(
                0,
                len(
                    words
                ),
                max_words,
            )
            if words[
                index:
                index + max_words
            ]
        ]

    @classmethod
    def _ensure_upload_ready_visual_variety(
        cls,
        *,
        visual_scenes: list[VisualScene],
        domain: str,
        family: str,
    ) -> None:
        """
        Long-form upload-readiness preflight.

        For 8+ scenes, require at least three visual treatments. This repairs
        the production plan itself instead of weakening the monetization gate.
        """
        if len(visual_scenes) < 8:
            return

        before = {
            scene.visual_type
            for scene in visual_scenes
        }

        if len(before) >= 3:
            print(
                "[VISUAL DIVERSITY] "
                f"preflight OK: {len(before)} visual types"
            )
            return

        if (
            domain in {"gaming", "cartoon"}
            or family == "creative"
        ):
            replacements = (
                (3, "editorial_summary"),
                (4, "infographic"),
                (6, "timeline_scene"),
                (8, "comparison_scene"),
            )

        elif (
            family in {
                "factual_real_media",
                "lifestyle_real_media",
            }
            or domain == "general"
        ):
            replacements = (
                (3, "infographic"),
                (5, "real_photo"),
                (7, "timeline_scene"),
                (8, "editorial_summary"),
            )

        elif family == "factual_editorial":
            replacements = (
                (3, "infographic"),
                (5, "comparison_scene"),
                (7, "timeline_scene"),
                (8, "editorial_summary"),
            )

        elif family == "data_finance":
            replacements = (
                (3, "finance_graphic"),
                (5, "comparison_scene"),
                (7, "infographic"),
                (8, "timeline_scene"),
            )

        elif family == "technical":
            replacements = (
                (3, "technical_diagram"),
                (5, "technical_workflow"),
                (7, "code"),
                (8, "infographic"),
            )

        else:
            replacements = (
                (3, "infographic"),
                (5, "timeline_scene"),
                (7, "comparison_scene"),
                (8, "editorial_summary"),
            )

        for scene_number, visual_type in replacements:
            index = scene_number - 1

            if index >= len(visual_scenes):
                continue

            scene = visual_scenes[index]
            scene.visual_type = visual_type
            scene.composition = cls._composition(
                visual_type=visual_type,
                domain=domain,
            )
            scene.style = cls._style(
                visual_type=visual_type,
                domain=domain,
            )
            scene.avoid = cls._avoid(
                domain=domain,
                visual_type=visual_type,
            )

            current = {
                item.visual_type
                for item in visual_scenes
            }

            if len(current) >= 3:
                break

        after = {
            scene.visual_type
            for scene in visual_scenes
        }

        print(
            "[VISUAL DIVERSITY] "
            f"preflight repaired: {len(before)} -> "
            f"{len(after)} visual types "
            f"({', '.join(sorted(after))})"
        )

        if len(after) < 3:
            raise RuntimeError(
                "Visual diversity preflight failed: "
                "long-form video still has fewer than 3 visual treatments."
            )

    @staticmethod
    def _visual_type(
        *,
        domain: str,
        family: str,
        topic: str,
        title: str,
        text: str,
        block_kind: str,
        scene_index: int,
        recent_types: list[str],
    ) -> str:
        value = (
            f"{topic} {title} {text}"
        ).lower()

        if ContentProductionAgent._use_natural_photo(
            family=family,
            domain=domain,
            scene_index=scene_index,
            block_kind=block_kind,
        ):
            candidate = "real_photo"

        elif domain == "sports":
            if (
                block_kind == "hook"
                and (
                    " vs "
                    in f" {topic.lower()} "
                    or " versus "
                    in f" {topic.lower()} "
                )
            ):
                candidate = "sports_matchup"
            elif any(
                marker in value
                for marker in (
                    "date",
                    "kickoff",
                    "minute",
                    "first half",
                    "second half",
                    "timeline",
                )
            ):
                candidate = "sports_timeline"
            else:
                candidate = "sports_fact_card"

        elif domain == "legal":
            if any(
                marker in value
                for marker in (
                    "timeline",
                    "hearing",
                    "filed",
                    "order",
                    "judgment",
                    "judgement",
                    "date",
                    "later",
                    "earlier",
                    "appeal",
                )
            ):
                candidate = "legal_timeline"
            elif any(
                marker in value
                for marker in (
                    "difference",
                    "versus",
                    " vs ",
                    "compare",
                    "argument",
                    "side",
                )
            ):
                candidate = "legal_comparison"
            else:
                candidate = "legal_fact_card"

        elif domain == "education":
            if block_kind == "hook":
                candidate = "education_hero"
            elif any(
                marker in value
                for marker in (
                    "eligibility",
                    "eligible",
                    "income",
                    "category",
                    "criteria",
                )
            ):
                candidate = "education_eligibility"
            elif any(
                marker in value
                for marker in (
                    "deadline",
                    "last date",
                    "date",
                    "schedule",
                    "timeline",
                )
            ):
                candidate = "education_deadline"
            elif any(
                marker in value
                for marker in (
                    "document",
                    "certificate",
                    "aadhaar",
                    "bank account",
                    "marksheet",
                )
            ):
                candidate = "education_documents"
            elif any(
                marker in value
                for marker in (
                    "portal",
                    "website",
                    "apply",
                    "application",
                    "register",
                    "registration",
                    "status",
                )
            ):
                candidate = "education_portal"
            elif block_kind in {
                "conclusion",
                "cta",
            }:
                candidate = "education_next_steps"
            else:
                candidate = (
                    "education_student_context"
                    if scene_index % 2
                    else "education_process"
                )

        elif domain == "product":
            if block_kind == "hook":
                candidate = "product_hero"
            elif any(
                marker in value
                for marker in (
                    "design",
                    "case",
                    "dial",
                    "finish",
                    "weight",
                    "color",
                    "colour",
                    "build",
                    "stem",
                    "fit",
                )
            ):
                candidate = "product_macro"
            elif any(
                marker in value
                for marker in (
                    "anc",
                    "noise cancellation",
                    "driver",
                    "audio",
                    "sound",
                    "bass",
                    "spatial",
                    "microphone",
                    "voice",
                )
            ):
                candidate = "product_audio"
            elif any(
                marker in value
                for marker in (
                    "battery",
                    "charge",
                    "charging",
                    "hours",
                    "playback",
                    "usb",
                )
            ):
                candidate = "product_battery"
            elif any(
                marker in value
                for marker in (
                    "gaming",
                    "latency",
                    "game",
                )
            ):
                candidate = "product_gaming"
            elif any(
                marker in value
                for marker in (
                    "app",
                    "eq",
                    "equalizer",
                    "equaliser",
                    "bluetooth",
                    "pair",
                    "connect",
                    "custom",
                )
            ):
                candidate = "product_app"
            elif any(
                marker in value
                for marker in (
                    "price",
                    "value",
                    "worth",
                    "competition",
                    "competitor",
                    "versus",
                    " vs ",
                    "cheaper",
                    "cost",
                )
            ):
                candidate = "product_value"
            elif block_kind in {
                "conclusion",
                "cta",
            }:
                candidate = "product_verdict"
            else:
                candidate = (
                    "product_lifestyle"
                    if scene_index % 2
                    else "product_feature"
                )

        elif domain == "finance":
            candidate = (
                "finance_graphic"
                if scene_index
                % 3
                else "infographic"
            )

        elif domain == "news":
            if any(
                marker in value
                for marker in (
                    "timeline",
                    "date",
                    "reported",
                    "later",
                    "earlier",
                    "sequence",
                )
            ):
                candidate = "timeline_scene"
            elif any(
                marker in value
                for marker in (
                    "compare",
                    "versus",
                    "difference",
                )
            ):
                candidate = "comparison_scene"
            else:
                candidate = (
                    "news_graphic"
                    if scene_index
                    % 3
                    else "infographic"
                )

        elif domain == "technical":
            if any(
                marker in value
                for marker in (
                    "code",
                    "python",
                    "javascript",
                    "playwright",
                    "selenium",
                    "command",
                    "terminal",
                )
            ):
                candidate = "code"
            elif any(
                marker in value
                for marker in (
                    "architecture",
                    "component",
                    "integration",
                    "system",
                )
            ):
                candidate = "technical_diagram"
            else:
                candidate = "technical_workflow"

        elif domain == "cartoon":
            if block_kind == "hook":
                candidate = "cartoon"

            elif scene_index % 4 == 0:
                candidate = "infographic"

            elif scene_index % 3 == 0:
                candidate = "editorial_summary"

            else:
                candidate = "cartoon_scene"

        elif domain == "gaming":
            if block_kind == "hook":
                candidate = "gaming_key_art"

            elif any(
                marker in value
                for marker in (
                    "timeline",
                    "first",
                    "then",
                    "next",
                    "before",
                    "after",
                    "release",
                    "update",
                    "patch",
                    "season",
                )
            ):
                candidate = "timeline_scene"

            elif any(
                marker in value
                for marker in (
                    "compare",
                    "comparison",
                    "versus",
                    " vs ",
                    "difference",
                    "better",
                    "worse",
                )
            ):
                candidate = "comparison_scene"

            elif scene_index % 4 == 0:
                candidate = "infographic"

            elif scene_index % 3 == 0:
                candidate = "editorial_summary"

            else:
                candidate = "gaming_scene"

        elif family in {
            "factual_real_media",
            "lifestyle_real_media",
        }:
            # Rotate real reusable media with deterministic explainers so a
            # factual video does not become ten nearly identical cards.
            if scene_index in {
                1,
                2,
            } or scene_index % 3 == 0:
                candidate = "real_photo"
            elif any(
                marker in value
                for marker in (
                    "timeline",
                    "date",
                    "first",
                    "next",
                    "then",
                    "later",
                    "before",
                    "after",
                )
            ):
                candidate = "timeline_scene"
            elif any(
                marker in value
                for marker in (
                    "compare",
                    "difference",
                    "versus",
                    " vs ",
                    "better",
                    "worse",
                )
            ):
                candidate = "comparison_scene"
            else:
                candidate = "infographic"

        elif family == "factual_editorial":
            if any(
                marker in value
                for marker in (
                    "timeline",
                    "date",
                    "later",
                    "earlier",
                    "before",
                    "after",
                )
            ):
                candidate = "timeline_scene"
            elif any(
                marker in value
                for marker in (
                    "compare",
                    "difference",
                    "versus",
                    " vs ",
                )
            ):
                candidate = "comparison_scene"
            else:
                candidate = "news_graphic"

        elif family == "creative":
            if block_kind == "hook":
                candidate = "explainer_illustration"

            elif any(
                marker in value
                for marker in (
                    "timeline",
                    "first",
                    "then",
                    "next",
                    "before",
                    "after",
                )
            ):
                candidate = "timeline_scene"

            elif any(
                marker in value
                for marker in (
                    "compare",
                    "comparison",
                    "difference",
                    "versus",
                    " vs ",
                )
            ):
                candidate = "comparison_scene"

            elif scene_index % 4 == 0:
                candidate = "infographic"

            elif scene_index % 3 == 0:
                candidate = "editorial_summary"

            else:
                candidate = "explainer_illustration"

        else:
            if any(
                marker in value
                for marker in (
                    "timeline",
                    "first",
                    "next",
                    "then",
                    "finally",
                )
            ):
                candidate = "timeline_scene"
            elif any(
                marker in value
                for marker in (
                    "compare",
                    "difference",
                    "versus",
                    " vs ",
                )
            ):
                candidate = "comparison_scene"
            else:
                candidate = (
                    "infographic"
                    if scene_index
                    % 3
                    else "news_graphic"
                )

        # Avoid three identical visual treatments in a row for factual content.
        if (
            domain
            not in {
                "cartoon",
                "gaming",
            }
            and len(
                recent_types
            )
            >= 2
            and recent_types[-1]
            == recent_types[-2]
            == candidate
        ):
            alternates = {
                "sports_fact_card": "sports_timeline",
                "sports_timeline": "sports_fact_card",
                "legal_fact_card": "legal_timeline",
                "legal_timeline": "legal_fact_card",
                "education_student_context": "education_process",
                "education_process": "education_student_context",
                "education_eligibility": "education_process",
                "product_feature": "product_lifestyle",
                "product_lifestyle": "product_feature",
                "product_audio": "product_macro",
                "product_macro": "product_feature",
                "finance_graphic": "infographic",
                "news_graphic": "infographic",
                "infographic": "news_graphic",
            }
            candidate = alternates.get(
                candidate,
                candidate,
            )

        return candidate

    @classmethod
    def _key_elements(
        cls,
        *,
        topic: str,
        section_name: str,
        text: str,
        domain: str,
    ) -> list[str]:
        values: list[str] = []

        def add(
            value: str,
        ) -> None:
            clean = re.sub(
                r"\s+",
                " ",
                value,
            ).strip(
                " .,:;!?-–—"
            )

            if (
                clean
                and clean.lower()
                not in {
                    item.lower()
                    for item in values
                }
            ):
                values.append(
                    clean[:80]
                )

        add(
            topic
        )

        if (
            section_name
            and section_name.lower()
            not in {
                "context",
                "next",
                "what it means",
            }
        ):
            add(
                section_name
            )

        entities = re.findall(
            r"\b(?:[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÿ0-9.'&’()-]*"
            r"(?:\s+[A-ZÀ-ÖØ-Ý0-9][A-Za-zÀ-ÿ0-9.'&’()-]*){0,3})\b",
            text,
        )

        for entity in entities:
            add(
                entity
            )
            if len(
                values
            ) >= 5:
                return values

        words = [
            word.lower()
            for word in re.findall(
                r"[A-Za-zÀ-ÿ\u0900-\u097F]{4,}",
                text,
            )
        ]

        counts = Counter(
            word
            for word in words
            if word
            not in STOP_WORDS
        )

        for word, _ in counts.most_common(
            8
        ):
            add(
                word
            )
            if len(
                values
            ) >= 5:
                break

        domain_label = {
            "legal": "legal process",
            "sports": "match context",
            "finance": "market context",
            "news": "current update",
            "technical": "system flow",
            "product": "product feature",
            "education": "scholarship guidance",
            "cartoon": "story action",
            "gaming": "game context",
        }.get(
            domain
        )

        if (
            domain_label
            and len(
                values
            )
            < 3
        ):
            add(
                domain_label
            )

        return values[
            :5
        ] or [
            topic
        ]

    @staticmethod
    def _scene_title(
        *,
        topic: str,
        section_name: str,
        chunk_index: int,
        chunk_count: int,
        block_kind: str,
    ) -> str:
        if block_kind == "hook":
            base = topic
        elif block_kind == "cta":
            base = "What to Watch Next"
        else:
            base = (
                section_name
                or topic
            )

        if chunk_count <= 1:
            return base[:90]

        return (
            f"{base} — {chunk_index}"
        )[:90]

    @staticmethod
    def _subject(
        *,
        topic: str,
        section_name: str,
        elements: list[str],
    ) -> str:
        primary = (
            elements[0]
            if elements
            else topic
        )

        if (
            section_name
            and section_name.lower()
            not in primary.lower()
        ):
            return (
                f"{primary}: {section_name}"
            )[:150]

        return primary[:150]

    @staticmethod
    def _use_natural_photo(
        *,
        family: str,
        domain: str,
        scene_index: int,
        block_kind: str,
    ) -> bool:
        """
        Universal natural-video policy.

        General factual topics now get a few real-media anchors too. The
        public-media provider's semantic relevance gate still rejects an
        unrelated image, so this does not trade relevance for variety.
        """
        if domain == "general":
            return scene_index in {
                1,
                2,
                5,
                8,
            }

        if family == "factual_real_media":
            return scene_index in {
                1,
                2,
                4,
                6,
                8,
                10,
            }

        if family == "lifestyle_real_media":
            return scene_index in {
                1,
                2,
                3,
                5,
                7,
                9,
            }

        if family == "factual_editorial":
            return scene_index in {
                1,
                6,
            }

        if family == "data_finance":
            return scene_index in {
                1,
                7,
            }

        if family == "product_cinematic":
            return scene_index in {
                1,
                6,
            }

        # technical and creative families intentionally stay diagram/art-first.
        return False

    @staticmethod
    def _composition(
        *,
        visual_type: str,
        domain: str,
    ) -> str:
        if visual_type == "real_photo":
            return (
                "Natural full-screen documentary/B-roll composition. Let the real scene carry the story; "
                "no presentation card, no paragraph overlay, no fake event recreation."
            )

        if visual_type == "education_hero":
            return (
                "Full-screen student/education context with one clear scholarship idea, "
                "minimal overlay, no classroom PowerPoint slide."
            )

        if visual_type in {
            "education_eligibility",
            "education_deadline",
            "education_documents",
            "education_portal",
            "education_process",
            "education_next_steps",
        }:
            return (
                "Clear public-service explainer using student/document/portal context with "
                "one visual idea and at most a few short labels; avoid paragraph-heavy cards."
            )

        if visual_type == "education_student_context":
            return (
                "Natural student/campus/study context with a concise factual overlay derived "
                "from narration; no fake institutional logo or fake document."
            )

        if visual_type == "product_hero":
            return (
                "Premium full-screen product hero shot, three-quarter angle, clean studio environment, "
                "strong foreground separation, generous negative space, no presentation-card layout."
            )

        if visual_type == "product_macro":
            return (
                "Macro close-up of the product's most relevant physical detail from the narration; "
                "shallow but controlled depth, crisp edges, tactile material detail."
            )

        if visual_type in {
            "product_audio",
            "product_battery",
            "product_gaming",
            "product_app",
            "product_feature",
        }:
            return (
                "Product remains visibly dominant while the feature is shown through a cinematic use-case "
                "or visual metaphor; one small metric badge maximum, no large educational slide."
            )

        if visual_type == "product_lifestyle":
            return (
                "Lifestyle scene showing the product naturally in use, with the product clearly visible "
                "and visually consistent with the topic."
            )

        if visual_type in {
            "product_value",
            "product_verdict",
        }:
            return (
                "Editorial product-review composition with the product hero on one side and a concise "
                "value/verdict cue on the other; no spreadsheet or finance chart."
            )

        if "timeline" in visual_type:
            return (
                "Horizontal three-stage timeline with one large idea per stage; "
                "use only details present in the narration."
            )

        if "comparison" in visual_type:
            return (
                "Two-column comparison with large headings and concise narration-derived points."
            )

        if visual_type == "sports_matchup":
            return (
                "Two-sided matchup layout with the two named teams separated by a central VS marker."
            )

        if visual_type in {
            "sports_fact_card",
            "legal_fact_card",
            "news_graphic",
        }:
            return (
                "One dominant headline area plus one concise factual explanation area; minimal clutter."
            )

        if visual_type in {
            "finance_graphic",
            "infographic",
            "editorial_summary",
        }:
            return (
                "One clear focal statement supported by 2–3 large visual points; no invented numbers."
            )

        if visual_type in {
            "code",
            "technical_diagram",
            "technical_workflow",
        }:
            return (
                "Large readable technical subject centered, with only the components needed to explain this narration."
            )

        return (
            "One dominant subject with clear foreground/background separation and room for subtle motion."
        )

    @staticmethod
    def _style(
        *,
        visual_type: str,
        domain: str,
    ) -> str:
        family = domain_family(
            domain
        )

        if family == "factual_real_media":
            return (
                "premium documentary/editorial YouTube visual, real-world context where reusable media exists, "
                "minimal overlays, one clear idea, cinematic rather than slide-like"
            )

        if family == "lifestyle_real_media":
            return (
                "premium lifestyle editorial visual, natural real-world context, cinematic composition, "
                "minimal text and strong subject focus"
            )

        if family == "factual_editorial":
            return (
                "premium factual explainer, restrained editorial design, one clear visual claim, "
                "minimal text and no decorative fake documentary imagery"
            )

        if domain == "education":
            return (
                "premium factual education/public-service explainer, student-focused photography "
                "mixed with clean process graphics, modern and trustworthy, not a classroom slide"
            )

        if domain == "product":
            return (
                "premium consumer-tech commercial photography and review cinematography, realistic materials, "
                "clean modern studio lighting, high-end gadget launch aesthetic, product always clearly visible"
            )

        if domain == "legal":
            return (
                "clean premium legal-news explainer, 1080p, restrained editorial design, highly readable"
            )

        if domain == "sports":
            return (
                "premium sports editorial explainer, 1080p, strong matchup hierarchy, highly readable"
            )

        if domain == "finance":
            return (
                "premium financial editorial graphic, 1080p, clean chart-like hierarchy without fake data"
            )

        if domain == "news":
            return (
                "premium current-affairs editorial graphic, 1080p, factual and highly readable"
            )

        if domain == "technical":
            return (
                "clean professional technical visualization, 1080p, readable engineering structure"
            )

        if domain == "cartoon":
            return (
                "original polished cartoon illustration with clear storytelling and crisp linework"
            )

        if domain == "gaming":
            return (
                "original game-inspired editorial key art with a clear focal subject and crisp detail"
            )

        return (
            "clean premium YouTube explainer visual with one immediately understandable idea"
        )

    @staticmethod
    def _avoid(
        *,
        domain: str,
        visual_type: str,
    ) -> list[str]:
        family = domain_family(
            domain
        )

        common = [
            "unrelated people",
            "tiny unreadable paragraphs",
            "visual clutter",
            "blurred subject",
            "watermark",
        ]

        if family in {
            "factual_real_media",
            "factual_editorial",
            "data_finance",
            "lifestyle_real_media",
        }:
            common.extend(
                [
                    "invented quote",
                    "invented statistic",
                    "invented official logo",
                    "fake screenshot presented as real",
                ]
            )

        if domain in {
            "legal",
            "news",
            "sports",
            "finance",
            "product",
            "education",
        }:
            common.extend(
                [
                    "invented facts",
                    "invented quotes",
                    "invented scores or numbers",
                    "fake documentary event",
                ]
            )

        if domain == "legal":
            common.extend(
                [
                    "invented court seal",
                    "invented judge portrait",
                    "fake legal document text",
                ]
            )

        if domain == "education":
            common.extend(
                [
                    "fake government logo",
                    "fake scholarship portal screenshot",
                    "invented eligibility rule",
                    "invented deadline",
                    "fake certificate text",
                    "giant classroom slide",
                ]
            )

        if domain == "product":
            common.extend(
                [
                    "finance chart",
                    "stock-market graph",
                    "classroom slide",
                    "giant paragraph card",
                    "invented brand logo",
                    "invented specification number",
                    "different unrelated gadget",
                ]
            )

        return common

    @staticmethod
    def _thumbnail_prompt(
        *,
        topic: str,
        title: str,
        domain: str,
    ) -> str:
        if domain in {
            "legal",
            "news",
            "sports",
            "finance",
            "technical",
            "product",
            "education",
        }:
            return (
                f"Premium factual YouTube thumbnail for {topic}. "
                f"Title context: {title}. One immediately understandable focal idea, "
                "large mobile-readable hierarchy, no invented quote, score, verdict, "
                "number, logo, expression, or event."
            )

        return (
            f"Premium original YouTube thumbnail for {topic}. "
            "One clear focal subject, simple composition, strong separation, "
            "no copied protected character art, no watermark."
        )

    @staticmethod
    def _youtube_description(
        *,
        description_opening: str,
        script: Any,
    ) -> str:
        pieces = []

        if description_opening:
            pieces.append(
                description_opening
            )

        if script.introduction.strip():
            pieces.append(
                script.introduction.strip()
            )

        conclusion = script.conclusion.strip()

        if conclusion:
            pieces.append(
                conclusion
            )

        clean = "\n\n".join(
            piece
            for piece in pieces
            if piece
        )

        return clean[:1800]

    @staticmethod
    def _youtube_tags(
        *,
        topic: str,
        script_title: str,
        domain: str,
    ) -> list[str]:
        tags = [
            topic.strip(),
            domain,
        ]

        words = unicode_tokens(
            (
                topic
                + " "
                + script_title
            ),
            min_length=3,
        )

        for word in words:
            if (
                word.lower()
                in STOP_WORDS
            ):
                continue

            if not any(
                existing.lower()
                == word.lower()
                for existing in tags
            ):
                tags.append(
                    word
                )

            if len(
                tags
            ) >= 12:
                break

        return tags

    @staticmethod
    def _words_per_minute(
        state: WorkflowState,
    ) -> int:
        audience = (
            state.strategy.audience
            if state.strategy is not None
            else ""
        ).lower()

        if any(
            marker in audience
            for marker in (
                "hindi",
                "hinglish",
                "hi_in",
            )
        ):
            return 150

        return 170

    @classmethod
    def _duration_seconds(
        cls,
        text: str,
        wpm: int,
    ) -> int:
        words = max(
            1,
            cls._word_count(
                text
            ),
        )

        return max(
            1,
            min(
                600,
                math.ceil(
                    words
                    / max(
                        1,
                        wpm,
                    )
                    * 60
                ),
            ),
        )

    @staticmethod
    def _word_count(
        text: str,
    ) -> int:
        words = re.findall(
            r"\b[\w@./+-]+\b",
            text,
            flags=re.UNICODE,
        )

        if words:
            return len(
                words
            )

        # Fallback for scripts without whitespace segmentation.
        return max(
            1,
            len(
                text.strip()
            )
            // 3,
        )
