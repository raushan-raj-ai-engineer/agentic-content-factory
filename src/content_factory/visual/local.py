from __future__ import annotations

import asyncio
import gc
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from PIL import Image

from content_factory.visual.base import VisualProvider
from content_factory.visual.compositor import PremiumSceneCompositor
from content_factory.visual.product_compositor import ProductSceneCompositor
from content_factory.visual.editorial import ViewerGraphicRenderer
from content_factory.visual.premium_generator import PremiumCreativeGenerator
from content_factory.visual.public_media import WikimediaCommonsProvider
from content_factory.visual.quality import (
    dimensions_ok,
    prepare_for_video,
    sharpness_score,
)
from content_factory.visual.semantic_router import (
    VisualDecision,
    decide_visual_route,
)
from content_factory.visual.domain_registry import (
    domain_family,
    prefers_public_media,
)
from content_factory.visual.technical import TechnicalVisualRenderer
from content_factory.visual.study_backdrop import StudyBackdropRenderer


class LocalVisualProvider(VisualProvider):
    """
    PREMIUM VISUAL ENGINE V6

    Factual:
      real reusable media where relevant + cinematic compositing
      otherwise domain-specific 1080p editorial visuals

    Study:
      deterministic cinematic vector backdrops + semantic Manim exact text
      optional one-scene textless MLX hero (off by default)

    Creative/non-study:
      Apple-native MLX Z-Image-Turbo where appropriate

    The goal is to remove garbled AI text and the "cheap AI slideshow" look.
    """

    MIN_SHARPNESS = 24.0
    CACHE_VERSION = 14

    def __init__(
        self,
    ) -> None:
        self._technical_renderer = TechnicalVisualRenderer()
        self._study_backdrop = StudyBackdropRenderer()
        self._editorial_renderer = ViewerGraphicRenderer()
        self._public_media = WikimediaCommonsProvider()
        self._compositor = PremiumSceneCompositor()
        self._product_compositor = ProductSceneCompositor()
        self._premium = PremiumCreativeGenerator()

        self._cache_root = Path(
            os.getenv(
                "CONTENT_FACTORY_VISUAL_CACHE",
                ".cache/content_factory/visual",
            )
        )
        self._cache_root.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._context_topic = ""
        self._context_domain = "general"
        self._study_mode = False

        print(
            "[VISUAL] Premium Visual Engine V6 enabled."
        )

    def set_context(
        self,
        *,
        topic: str = "",
        domain: str | None = None,
        study_mode: bool = False,
    ) -> None:
        self._context_topic = (
            topic
            or ""
        )

        detected = (
            domain
            or ""
        ).strip().lower()

        self._context_domain = (
            detected
            or "general"
        )
        self._study_mode = bool(study_mode)

        print(
            f"[VISUAL] Run context: "
            f"domain={self._context_domain}, "
            f"topic={self._context_topic!r}"
        )
        if self._study_mode:
            ai_hero = os.getenv("CONTENT_FACTORY_STUDY_AI_HERO", "0").strip().lower()
            ai_hero_on = ai_hero in {"1", "true", "yes", "on"}
            print(
                "[STUDY VISUAL POLICY] exact-text deterministic backdrops + semantic Manim; "
                f"AI hero={'OPT-IN' if ai_hero_on else 'OFF'}; diffusion never renders teaching text."
            )
            if os.getenv("CONTENT_FACTORY_STUDY_HERO_VISUALS") is not None:
                print(
                    "[STUDY VISUAL POLICY] CONTENT_FACTORY_STUDY_HERO_VISUALS is deprecated "
                    "and ignored; use CONTENT_FACTORY_STUDY_AI_HERO only for optional scene-1 ambience."
                )

    async def generate(
        self,
        prompt: str,
        output_path: str,
        *,
        title: str | None = None,
        description: str | None = None,
        visual_type: str | None = None,
    ) -> None:
        title = (
            title
            or "Explainer Scene"
        )
        description = (
            description
            or prompt
        )
        vtype = (
            visual_type
            or "cinematic_explainer"
        ).strip().lower()

        decision = decide_visual_route(
            title=title,
            description=description,
            prompt=prompt,
            visual_type=vtype,
            context_domain=self._context_domain,
        )

        scene_index = self._scene_index(
            output_path
        )

        cache_key = self._cache_key(
            prompt=prompt,
            title=title,
            description=description,
            visual_type=vtype,
            route=decision.route,
            domain=decision.domain,
        )

        if self._restore_cache(
            cache_key,
            output_path,
            decision,
        ):
            self._write_motion(
                output_path,
                mode=self._motion_mode(
                    decision,
                    public_photo=False,
                ),
            )
            return

        print(
            f"[VISUAL ROUTE] {title!r}: "
            f"{decision.domain} -> {decision.route}"
        )

        # -------------------------------------------------------------
        # Product/gadget scenes: premium local product-focused generation.
        # Never send a product video to finance/editorial slide rendering.
        # -------------------------------------------------------------
        if decision.route == "product":
            await self._generate_premium_product(
                title=title,
                description=description,
                prompt=prompt,
                visual_type=vtype,
                output_path=output_path,
                scene_index=scene_index,
            )

            self._store_cache(
                cache_key,
                output_path,
            )

            self._write_motion(
                output_path,
                mode=self._product_motion_mode(
                    vtype
                ),
            )
            return

        if decision.route == "public_photo":
            public_ok = await self._try_public_composite(
                title=title,
                description=description,
                prompt=prompt,
                output_path=output_path,
                decision=decision,
                scene_index=scene_index,
            )

            if public_ok:
                self._store_cache(
                    cache_key,
                    output_path,
                )
                self._write_motion(
                    output_path,
                    mode="photo_pan",
                )
                return

            family = domain_family(
                decision.domain
            )

            print(
                f"[VISUAL QA] No sufficiently relevant reusable media for {title!r}; "
                f"fallback family={family}."
            )

            if family == "product_cinematic":
                await self._generate_premium_product(
                    title=title,
                    description=description,
                    prompt=prompt,
                    visual_type="product_feature",
                    output_path=output_path,
                    scene_index=scene_index,
                )

                self._store_cache(
                    cache_key,
                    output_path,
                )
                self._write_motion(
                    output_path,
                    mode="product_feature",
                )
                return

            # Other factual families fall through to their deterministic
            # editorial renderer rather than accepting a wrong image.

        # -------------------------------------------------------------
        # Real-world factual scenes: use real reusable media periodically
        # instead of making every frame a dark card.
        # -------------------------------------------------------------
        if (
            prefers_public_media(
                decision.domain
            )
            and decision.route
            != "diffusion"
            and self._should_try_public_media(
                title=title,
                description=description,
                prompt=prompt,
                scene_index=scene_index,
            )
        ):
            public_ok = await self._try_public_composite(
                title=title,
                description=description,
                prompt=prompt,
                output_path=output_path,
                decision=decision,
                scene_index=scene_index,
            )

            if public_ok:
                self._store_cache(
                    cache_key,
                    output_path,
                )
                self._write_motion(
                    output_path,
                    mode="photo_pan",
                )
                return

        # -------------------------------------------------------------
        # Study technical visuals: deterministic by default.
        # Generative image models are not allowed to render instructional text.
        # Optional AI hero art is restricted to scene 1 and is textless.
        # -------------------------------------------------------------
        if decision.route == "technical":
            if self._study_mode:
                used_ai_hero = False
                if self._should_use_ai_study_hero(scene_index=scene_index):
                    try:
                        await self._generate_textless_study_hero(
                            title=title,
                            output_path=output_path,
                            scene_index=scene_index,
                        )
                        used_ai_hero = True
                        print(
                            f"[STUDY VISUAL] scene={scene_index} backend=local-ai-hero "
                            "text_policy=FORBIDDEN"
                        )
                    except Exception as exc:
                        print(
                            "[STUDY VISUAL] AI hero unavailable; deterministic backdrop selected: "
                            f"{exc}"
                        )
                if not used_ai_hero:
                    self._study_backdrop.render(
                        title=title,
                        description=description,
                        visual_type=vtype,
                        output_path=output_path,
                        topic=self._context_topic or title,
                        scene_index=scene_index,
                    )
                    print(
                        f"[STUDY VISUAL] scene={scene_index} backend=deterministic-vector "
                        "text_policy=MANIM_ONLY"
                    )
                if used_ai_hero:
                    prepare_for_video(output_path)
                self._report(
                    output_path,
                    "study_deterministic" if not used_ai_hero else "study_ai_hero",
                    True,
                    sharpness=sharpness_score(output_path),
                    extra={
                        "domain": decision.domain,
                        "semantic_clear": True,
                        "study_mode": True,
                        "instructional_text_generated_by_ai": False,
                    },
                )
                self._write_motion(output_path, mode="editorial_static")
                self._store_cache(cache_key, output_path)
                return

            self._technical_renderer.render(
                title=title,
                description=description,
                visual_type=self._technical_type(
                    vtype,
                    prompt,
                ),
                output_path=output_path,
                topic=self._context_topic or title,
            )
            prepare_for_video(
                output_path
            )

            self._report(
                output_path,
                "technical",
                True,
                sharpness=sharpness_score(
                    output_path
                ),
                extra={
                    "domain": decision.domain,
                    "semantic_clear": True,
                },
            )
            self._write_motion(
                output_path,
                mode="editorial_static",
            )

        # -------------------------------------------------------------
        # Creative image generation: premium MLX backend only.
        # -------------------------------------------------------------
        elif decision.route == "diffusion":
            await self._generate_premium_creative(
                title=title,
                description=description,
                prompt=prompt,
                visual_type=vtype,
                output_path=output_path,
                domain=decision.domain,
                scene_index=scene_index,
            )
            self._write_motion(
                output_path,
                mode="creative_push",
            )

        # -------------------------------------------------------------
        # Factual / explainable editorial frame.
        # -------------------------------------------------------------
        else:
            self._editorial_renderer.render(
                title=title,
                description=description,
                visual_type=self._editorial_type(
                    decision,
                    vtype,
                ),
                output_path=output_path,
                prompt=prompt,
            )

            prepare_for_video(
                output_path
            )

            self._report(
                output_path,
                decision.route,
                True,
                sharpness=sharpness_score(
                    output_path
                ),
                extra={
                    "domain": decision.domain,
                    "semantic_clear": True,
                },
            )

            self._write_motion(
                output_path,
                mode="editorial_static",
            )

        self._store_cache(
            cache_key,
            output_path,
        )


    def _should_use_ai_study_hero(self, *, scene_index: int) -> bool:
        """AI art is opt-in and limited to one textless opener per video."""
        enabled = os.getenv("CONTENT_FACTORY_STUDY_AI_HERO", "0").strip().lower()
        return (
            enabled in {"1", "true", "yes", "on"}
            and scene_index == 1
            and self._premium.available
        )

    async def _generate_textless_study_hero(
        self,
        *,
        title: str,
        output_path: str,
        scene_index: int,
    ) -> None:
        """Optional textless hero background. Never receives narration or labels."""
        topic = re.sub(r"[^A-Za-z0-9 +#&./_-]+", " ", self._context_topic or title)
        topic = re.sub(r"\s+", " ", topic).strip()[:90]
        premium_prompt = (
            "Cinematic abstract technology background for an educational video. "
            f"Concept: {topic}. "
            "Wide 16:9 composition, dark charcoal/navy environment, electric cyan and violet light, "
            "abstract connected systems, flowing data particles, geometric technology forms, depth and negative space. "
            "ABSOLUTELY NO TEXT, NO WORDS, NO LETTERS, NO NUMBERS, NO CAPTIONS, NO LABELS, "
            "NO CODE GLYPHS, NO SIGNAGE, NO LOGOS, NO WATERMARKS, NO UI PANELS WITH WRITING. "
            "Do not draw monitors or documents containing writing. Visual atmosphere only."
        )
        seed = self._stable_seed(title, topic, scene_index)
        await self._premium.generate(
            prompt=premium_prompt,
            output_path=output_path,
            seed=seed,
            width=1280,
            height=720,
            steps=6,
        )
        prepare_for_video(output_path)

    async def _generate_premium_product(
        self,
        *,
        title: str,
        description: str,
        prompt: str,
        visual_type: str,
        output_path: str,
        scene_index: int,
    ) -> None:
        if not self._premium.available:
            raise RuntimeError(
                "Product video selected but premium MLX visual backend "
                "is not installed. Run setup_premium_visual_model.sh."
            )

        topic = (
            self._context_topic
            or title
        )

        compact = re.sub(
            r"\s+",
            " ",
            description,
        ).strip()[:520]

        visual = visual_type.lower()

        if "hero" in visual:
            shot = (
                "premium studio hero product shot, product and charging/accessory case fully visible, "
                "three-quarter angle, dramatic rim lighting, glossy commercial launch photography"
            )
        elif "macro" in visual:
            shot = (
                "extreme macro product detail shot, tactile material texture, controls, hinge, ports or "
                "physical design detail relevant to the narration, crisp micro-contrast"
            )
        elif "audio" in visual:
            shot = (
                "cinematic audio-feature visualization with the product dominant in foreground, subtle "
                "sound-wave environment and noise-isolation context, no infographic chart"
            )
        elif "battery" in visual:
            shot = (
                "premium charging/battery lifestyle setup on a modern desk, product case clearly visible, "
                "soft practical lighting, energetic but believable commercial photography"
            )
        elif "gaming" in visual:
            shot = (
                "product used in a gaming setup with phone or handheld device, neon practical light, "
                "low-latency lifestyle feel, product remains clearly visible"
            )
        elif "app" in visual:
            shot = (
                "product beside a modern smartphone showing a generic audio-control interface with no "
                "invented brand UI text, clean technology review aesthetic"
            )
        elif "value" in visual:
            shot = (
                "premium product hero on a clean review desk with subtle price/value atmosphere, "
                "no stock chart, no finance graph, no retail-site screenshot"
            )
        elif "verdict" in visual:
            shot = (
                "confident final hero shot of the product on a premium dark-to-light studio background, "
                "strong silhouette and polished review-video ending"
            )
        else:
            shot = (
                "cinematic real-life product-use scene, premium consumer technology commercial photography, "
                "product clearly identifiable and visually dominant"
            )

        premium_prompt = (
            f"{shot}. "
            f"Topic product: {topic}. "
            f"Evidence-derived scene information: {compact}. "
            "Represent the correct product CATEGORY and all physical details explicitly supported by the "
            "scene information. If an exact branded logo or exact physical detail is uncertain, do not invent "
            "a readable logo; keep branding subtle/abstract while preserving the product category. "
            "16:9, photorealistic materials, crisp edges, realistic scale, premium commercial art direction, "
            "clean background, no educational slide, no giant text box, no finance chart, no stock graph, "
            "no watermark, no duplicated product, no random unrelated gadget."
        )

        seed = self._stable_seed(
            title,
            description,
            scene_index,
        )

        result = await self._premium.generate(
            prompt=premium_prompt,
            output_path=output_path,
            seed=seed,
            width=1280,
            height=720,
            steps=9,
        )

        prepare_for_video(
            output_path
        )

        score = sharpness_score(
            output_path
        )

        if score < self.MIN_SHARPNESS:
            retry_seed = (
                seed
                + 7919
            ) % 2_147_483_647

            await self._premium.generate(
                prompt=premium_prompt,
                output_path=output_path,
                seed=retry_seed,
                width=1280,
                height=720,
                steps=9,
            )

            prepare_for_video(
                output_path
            )
            score = sharpness_score(
                output_path
            )

        if score < self.MIN_SHARPNESS:
            raise RuntimeError(
                f"Premium product scene failed sharpness QA: "
                f"{title!r}, score={score:.1f}"
            )

        self._product_compositor.compose(
            image_path=output_path,
            title=title,
            description=description,
            visual_type=visual_type,
        )

        self._report(
            output_path,
            "product_z_image_mlx",
            True,
            sharpness=sharpness_score(
                output_path
            ),
            extra={
                "domain": "product",
                "semantic_route": "product",
                "model": "Tongyi-MAI/Z-Image-Turbo",
                "backend": "mflux",
                "steps": 9,
                "width": 1280,
                "height": 720,
                "quantize": result.get(
                    "quantize"
                ),
            },
        )

        print(
            f"[VISUAL QA] Premium product scene accepted: "
            f"{title!r}"
        )

    @staticmethod
    def _product_motion_mode(
        visual_type: str,
    ) -> str:
        value = visual_type.lower()

        if "macro" in value:
            return "product_macro"

        if "lifestyle" in value or "gaming" in value:
            return "product_lifestyle"

        if "hero" in value or "verdict" in value:
            return "product_hero"

        return "product_feature"

    async def _generate_premium_creative(
        self,
        *,
        title: str,
        description: str,
        prompt: str,
        visual_type: str,
        output_path: str,
        domain: str,
        scene_index: int,
    ) -> None:
        if not self._premium.available:
            raise RuntimeError(
                "Creative video selected but the premium Apple-Silicon visual "
                "backend is not installed. Run:\n"
                "bash "
                "scripts/setup_premium_visual_model.sh\n"
                "V4 intentionally does not fall back to the old low-quality "
                "SD-Turbo path."
            )

        premium_prompt = self._premium_prompt(
            title=title,
            description=description,
            prompt=prompt,
            visual_type=visual_type,
            domain=domain,
        )

        seed = self._stable_seed(
            title,
            description,
            scene_index,
        )

        result = await self._premium.generate(
            prompt=premium_prompt,
            output_path=output_path,
            seed=seed,
            width=1280,
            height=720,
            steps=9,
        )

        prepare_for_video(
            output_path
        )

        score = sharpness_score(
            output_path
        )

        if score < self.MIN_SHARPNESS:
            # One different seed only when local QA says the first image is
            # objectively too soft. We do not regenerate every scene twice.
            retry_seed = (
                seed
                + 7919
            ) % 2_147_483_647

            print(
                f"[VISUAL QA] Premium scene soft "
                f"({score:.1f}); retrying one alternate seed."
            )

            await self._premium.generate(
                prompt=premium_prompt,
                output_path=output_path,
                seed=retry_seed,
                width=1280,
                height=720,
                steps=9,
            )

            prepare_for_video(
                output_path
            )

            score = sharpness_score(
                output_path
            )

        if score < self.MIN_SHARPNESS:
            raise RuntimeError(
                f"Premium creative scene did not pass sharpness QA: "
                f"{title!r}, score={score:.1f}"
            )

        self._report(
            output_path,
            "z_image_turbo_mlx",
            True,
            sharpness=score,
            extra={
                "domain": domain,
                "semantic_route": "premium_creative",
                "model": "Tongyi-MAI/Z-Image-Turbo",
                "backend": "mflux",
                "steps": 9,
                "width": 1280,
                "height": 720,
                "quantize": result.get(
                    "quantize"
                ),
            },
        )

        print(
            f"[VISUAL QA] Premium creative accepted: "
            f"{title!r}, sharpness={score:.1f}"
        )

    async def _try_public_composite(
        self,
        *,
        title: str,
        description: str,
        prompt: str,
        output_path: str,
        decision: VisualDecision,
        scene_index: int,
    ) -> bool:
        query = self._public_query(
            title=title,
            description=description,
            prompt=prompt,
            domain=decision.domain,
        )

        shot_count = max(
            1,
            min(
                3,
                int(
                    os.getenv(
                        "CONTENT_FACTORY_BROLL_SHOTS",
                        "3",
                    )
                ),
            ),
        )

        output = Path(
            output_path
        )

        temp_paths = [
            str(
                output.with_name(
                    f".{output.stem}.source-{index:02d}{output.suffix}"
                )
            )
            for index in range(
                1,
                shot_count + 1,
            )
        ]

        public_results = await self._public_media.fetch_many(
            query=query,
            output_paths=temp_paths,
            limit=shot_count,
        )

        if not public_results:
            return False

        accepted_targets: list[
            Path
        ] = []

        try:
            for shot_index, public in enumerate(
                public_results,
                start=1,
            ):
                source = Path(
                    temp_paths[
                        shot_index - 1
                    ]
                )

                if not source.is_file():
                    continue

                if not dimensions_ok(
                    source,
                    min_width=900,
                    min_height=500,
                ):
                    continue

                target = (
                    output
                    if shot_index == 1
                    else output.with_name(
                        f"{output.stem}.shot{shot_index:02d}{output.suffix}"
                    )
                )

                target.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                shutil.copy2(
                    source,
                    target,
                )

                source_sidecar = source.with_suffix(
                    source.suffix
                    + ".source.json"
                )
                target_sidecar = target.with_suffix(
                    target.suffix
                    + ".source.json"
                )

                if source_sidecar.is_file():
                    shutil.copy2(
                        source_sidecar,
                        target_sidecar,
                    )

                self._compositor.compose_public_photo(
                    image_path=target,
                    title=title,
                    summary=description,
                    domain=decision.domain,
                    scene_index=scene_index,
                    show_overlay=(
                        shot_index == 1
                        and scene_index in {
                            1,
                            10,
                        }
                    ),
                )

                score = sharpness_score(
                    target
                )

                if score < self.MIN_SHARPNESS:
                    target.unlink(
                        missing_ok=True
                    )
                    target_sidecar.unlink(
                        missing_ok=True
                    )
                    continue

                accepted_targets.append(
                    target
                )

            if not accepted_targets:
                return False

            # First accepted image is the canonical scene path.
            if accepted_targets[0] != output:
                shutil.copy2(
                    accepted_targets[0],
                    output,
                )

            manifest = output.with_suffix(
                output.suffix
                + ".shots.json"
            )

            manifest.write_text(
                json.dumps(
                    {
                        "mode": "cinematic_broll",
                        "shots": [
                            {
                                "path": path.name,
                                "motion": "photo_pan",
                            }
                            for path in accepted_targets
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            primary_score = sharpness_score(
                output
            )

            self._report(
                output_path,
                "wikimedia_cinematic_broll",
                True,
                sharpness=primary_score,
                extra={
                    "domain": decision.domain,
                    "source": public_results[0].source_page,
                    "license": public_results[0].license_name,
                    "relevance_score": public_results[0].relevance_score,
                    "matched_terms": list(
                        public_results[0].matched_terms
                    ),
                    "semantic_clear": True,
                    "broll_shots": len(
                        accepted_targets
                    ),
                },
            )

            print(
                "[VISUAL QA] Cinematic B-roll accepted: "
                f"{title!r}, shots={len(accepted_targets)}"
            )

            return True

        finally:
            for value in temp_paths:
                source = Path(
                    value
                )
                source.unlink(
                    missing_ok=True
                )
                source.with_suffix(
                    source.suffix
                    + ".source.json"
                ).unlink(
                    missing_ok=True
                )

    def _should_try_public_media(
        self,
        *,
        title: str,
        description: str,
        prompt: str,
        scene_index: int,
    ) -> bool:
        # Opening gets the strongest chance to use real contextual media.
        if scene_index <= 2:
            return True

        # Then use roughly one real-media composition every 3 factual scenes.
        if scene_index % 3 == 0:
            return True

        combined = (
            title
            + " "
            + description
            + " "
            + prompt
        )

        entities = re.findall(
            r"\b(?:[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÿ0-9.&'’()-]*"
            r"(?:\s+[A-ZÀ-ÖØ-Ý0-9][A-Za-zÀ-ÿ0-9.&'’()-]*){0,3})\b",
            combined,
        )

        return len(
            entities
        ) >= 2

    def _public_query(
        self,
        *,
        title: str,
        description: str,
        prompt: str,
        domain: str,
    ) -> str:
        """
        Build a topic-first query. Generic domain suffixes such as
        "sports football" previously caused wrong but sharp images.
        """
        topic = re.sub(
            r"\s+",
            " ",
            self._context_topic
            or "",
        ).strip()

        scene_title = re.sub(
            r"\s+",
            " ",
            title
            or "",
        ).strip()

        stop = {
            "the",
            "and",
            "for",
            "with",
            "from",
            "about",
            "this",
            "that",
            "what",
            "why",
            "how",
            "explained",
            "update",
            "scene",
            "context",
            "key",
            "guide",
            "overview",
        }

        topic_tokens = {
            token.lower()
            for token in re.findall(
                r"[A-Za-zÀ-ÿ0-9]{3,}",
                topic,
            )
        }

        extra = []

        for token in re.findall(
            r"[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9'’-]{2,}",
            scene_title,
        ):
            lower = token.lower()

            if lower in stop:
                continue

            if lower in topic_tokens:
                continue

            if lower in {
                item.lower()
                for item in extra
            }:
                continue

            extra.append(
                token
            )

            if len(
                extra
            ) >= 3:
                break

        query = " ".join(
            [
                topic,
                *extra,
            ]
        ).strip()

        if not query:
            query = scene_title

        return query[
            :160
        ]

    @staticmethod
    def _premium_prompt(
        *,
        title: str,
        description: str,
        prompt: str,
        visual_type: str,
        domain: str,
    ) -> str:
        subject_match = re.search(
            r"Subject:\s*(.+?)(?:\.\s|$)",
            prompt,
            flags=re.IGNORECASE,
        )

        subject = (
            subject_match.group(
                1
            ).strip()
            if subject_match
            else title
        )

        description = re.sub(
            r"\s+",
            " ",
            description,
        ).strip()[:420]

        hero = any(
            marker in visual_type
            for marker in (
                "hero",
                "key_art",
            )
        )

        if (
            domain == "cartoon"
            or "cartoon" in visual_type
            or "character" in visual_type
        ):
            style = (
                "high-end original animated cinematic frame, expressive "
                "character acting inside a believable environment, polished "
                "feature-film lighting and depth"
            )

        elif (
            domain == "gaming"
            or "gaming" in visual_type
        ):
            style = (
                (
                    "premium original game-inspired cinematic hero frame, "
                    "dramatic environment and strong focal action"
                )
                if hero
                else (
                    "cinematic in-world gameplay-style environmental shot, "
                    "natural camera perspective, believable scene depth, "
                    "subject interacting with the environment"
                )
            )

        else:
            style = (
                "cinematic documentary-style editorial image, realistic "
                "materials, natural camera perspective, environmental "
                "storytelling and professional art direction"
            )

        shot_language = (
            "hero composition with a bold focal subject"
            if hero
            else (
                "photographic shot language, candid moment, environmental "
                "context, off-center framing when useful, no poster pose"
            )
        )

        return (
            f"{style}. "
            f"{shot_language}. "
            f"Main subject: {subject}. "
            f"Visual story: {description}. "
            "16:9 cinematic frame, realistic lens perspective, foreground "
            "midground background separation, subtle depth of field, natural "
            "lighting, believable scale and anatomy, detailed textures, "
            "no presentation slide, no title card, no infographic layout, "
            "no text, no letters, no watermark, no collage, no duplicated "
            "people, no random unrelated objects, no blurry subject."
        )


    @staticmethod
    def _stable_seed(
        title: str,
        description: str,
        scene_index: int,
    ) -> int:
        digest = hashlib.sha256(
            (
                f"{title}|{description}|{scene_index}"
            ).encode(
                "utf-8"
            )
        ).digest()

        return int.from_bytes(
            digest[:4],
            "big",
        ) % 2_147_483_647


    def _cache_key(
        self,
        *,
        prompt: str,
        title: str,
        description: str,
        visual_type: str,
        route: str,
        domain: str,
    ) -> str:
        payload = {
            "cache_version": self.CACHE_VERSION,
            "topic": self._context_topic,
            "domain": domain,
            "route": route,
            "prompt": prompt,
            "title": title,
            "description": description,
            "visual_type": visual_type,
            "premium_model": "z-image-turbo-mlx",
            "premium_steps": 9,
            "premium_size": [
                1280,
                720,
            ],
            "final_size": [
                1920,
                1080,
            ],
        }

        return hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                ensure_ascii=False,
            ).encode(
                "utf-8"
            )
        ).hexdigest()


    def _restore_cache(
        self,
        cache_key: str,
        output_path: str,
        decision: VisualDecision,
    ) -> bool:
        image_cache = (
            self._cache_root
            / f"{cache_key}.png"
        )
        meta_cache = (
            self._cache_root
            / f"{cache_key}.json"
        )

        if (
            not image_cache.is_file()
            or not meta_cache.is_file()
        ):
            return False

        output = Path(
            output_path
        )
        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        shutil.copy2(
            image_cache,
            output,
        )

        sidecar_cache = (
            self._cache_root
            / f"{cache_key}.source.json"
        )

        if sidecar_cache.is_file():
            shutil.copy2(
                sidecar_cache,
                output.with_suffix(
                    output.suffix
                    + ".source.json"
                ),
            )

        shots_cache = (
            self._cache_root
            / f"{cache_key}.shots.json"
        )

        if shots_cache.is_file():
            cached_manifest = json.loads(
                shots_cache.read_text(
                    encoding="utf-8"
                )
            )

            restored = []

            for index, shot in enumerate(
                cached_manifest.get(
                    "shots",
                    []
                ),
                start=1,
            ):
                cache_shot = (
                    self._cache_root
                    / f"{cache_key}.shot{index:02d}.png"
                )

                if not cache_shot.is_file():
                    continue

                target = (
                    output
                    if index == 1
                    else output.with_name(
                        f"{output.stem}.shot{index:02d}{output.suffix}"
                    )
                )

                shutil.copy2(
                    cache_shot,
                    target,
                )

                restored.append(
                    {
                        "path": target.name,
                        "motion": str(
                            shot.get(
                                "motion",
                                "photo_pan",
                            )
                        ),
                    }
                )

            if restored:
                output.with_suffix(
                    output.suffix
                    + ".shots.json"
                ).write_text(
                    json.dumps(
                        {
                            "mode": "cinematic_broll",
                            "shots": restored,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )

        meta = json.loads(
            meta_cache.read_text(
                encoding="utf-8"
            )
        )

        self._report(
            output_path,
            str(
                meta.get(
                    "route",
                    decision.route,
                )
            ),
            True,
            sharpness=meta.get(
                "sharpness"
            ),
            extra={
                "cache_hit": True,
                "domain": decision.domain,
                "broll_cache": shots_cache.is_file(),
            },
        )

        print(
            f"[CACHE] Visual HIT: {output.name}"
        )

        return True


    def _store_cache(
        self,
        cache_key: str,
        output_path: str,
    ) -> None:
        output = Path(
            output_path
        )

        if not output.is_file():
            return

        record = self._latest_quality_record(
            output
        )

        if not record:
            return

        shutil.copy2(
            output,
            self._cache_root
            / f"{cache_key}.png",
        )

        (
            self._cache_root
            / f"{cache_key}.json"
        ).write_text(
            json.dumps(
                {
                    "route": record.get(
                        "route",
                        "unknown",
                    ),
                    "sharpness": record.get(
                        "sharpness"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        sidecar = output.with_suffix(
            output.suffix
            + ".source.json"
        )

        if sidecar.is_file():
            shutil.copy2(
                sidecar,
                self._cache_root
                / f"{cache_key}.source.json",
            )

        shots = output.with_suffix(
            output.suffix
            + ".shots.json"
        )

        if shots.is_file():
            manifest = json.loads(
                shots.read_text(
                    encoding="utf-8"
                )
            )

            cache_manifest = []

            for index, shot in enumerate(
                manifest.get(
                    "shots",
                    []
                ),
                start=1,
            ):
                shot_path = output.parent / str(
                    shot.get(
                        "path",
                        ""
                    )
                )

                if not shot_path.is_file():
                    continue

                shutil.copy2(
                    shot_path,
                    self._cache_root
                    / f"{cache_key}.shot{index:02d}.png",
                )

                cache_manifest.append(
                    {
                        "motion": str(
                            shot.get(
                                "motion",
                                "photo_pan",
                            )
                        ),
                    }
                )

            if cache_manifest:
                (
                    self._cache_root
                    / f"{cache_key}.shots.json"
                ).write_text(
                    json.dumps(
                        {
                            "mode": "cinematic_broll",
                            "shots": cache_manifest,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )

        print(
            f"[CACHE] Visual STORE: {output.name}"
        )


    async def release(
        self,
    ) -> None:
        await self._premium.release()
        gc.collect()


    @staticmethod
    def _scene_index(
        output_path: str,
    ) -> int:
        match = re.search(
            r"scene_(\d+)",
            Path(
                output_path
            ).stem,
        )

        return (
            int(
                match.group(
                    1
                )
            )
            if match
            else 1
        )


    @staticmethod
    def _motion_mode(
        decision: VisualDecision,
        *,
        public_photo: bool,
    ) -> str:
        if public_photo:
            return "photo_pan"

        if decision.route == "diffusion":
            return "creative_push"

        return "editorial_static"


    @staticmethod
    def _write_motion(
        output_path: str,
        *,
        mode: str,
    ) -> None:
        path = Path(
            output_path
        ).with_suffix(
            Path(
                output_path
            ).suffix
            + ".motion.json"
        )

        path.write_text(
            json.dumps(
                {
                    "mode": mode,
                },
                indent=2,
            ),
            encoding="utf-8",
        )


    @staticmethod
    def _editorial_type(
        decision: VisualDecision,
        requested: str,
    ) -> str:
        if "timeline" in requested:
            return "timeline"

        if "comparison" in requested:
            return "comparison"

        if "infographic" in requested:
            return "infographic"

        if "outro" in requested:
            return "outro"

        if decision.domain == "education":
            return "education"

        if decision.domain == "sports":
            return "sports"

        if decision.domain == "legal":
            return "legal"

        if decision.domain == "finance":
            return "finance"

        if decision.domain == "news":
            return "news"

        return "editorial"

    @staticmethod
    def _technical_type(
        visual_type: str,
        prompt: str,
    ) -> str:
        value = (
            visual_type
            + " "
            + prompt
        ).lower()

        if any(
            marker in value
            for marker in (
                "code",
                "terminal",
                "command",
            )
        ):
            return "code"

        if "architecture" in value:
            return "architecture"

        if any(
            marker in value
            for marker in (
                "dashboard",
                "metric",
            )
        ):
            return "dashboard"

        return "workflow"

    @staticmethod
    def _latest_quality_record(
        output: Path,
    ) -> dict[str, Any] | None:
        report = (
            output.parent
            / "scene_quality_report.jsonl"
        )

        if not report.exists():
            return None

        for line in reversed(
            report.read_text(
                encoding="utf-8"
            ).splitlines()
        ):
            try:
                record = json.loads(
                    line
                )
            except Exception:
                continue

            if (
                record.get(
                    "file"
                )
                == output.name
                and record.get(
                    "accepted",
                    True,
                )
            ):
                return record

        return None

    @staticmethod
    def _report(
        output_path: str,
        route: str,
        accepted: bool,
        *,
        sharpness: float | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        record: dict[str, Any] = {
            "file": Path(
                output_path
            ).name,
            "route": route,
            "accepted": accepted,
        }

        if sharpness is not None:
            record[
                "sharpness"
            ] = round(
                float(
                    sharpness
                ),
                2,
            )

        if extra:
            record.update(
                extra
            )

        report = (
            Path(
                output_path
            ).parent
            / "scene_quality_report.jsonl"
        )

        with report.open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                )
                + "\n"
            )
