from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from content_factory.agents.base import Agent
from content_factory.models.content import (
    VoiceArtifact,
    VoiceGenerationResult,
)
from content_factory.orchestration.state import WorkflowState
from content_factory.utils.artifact_paths import artifact_subdir
from content_factory.voice.base import VoiceProvider
from content_factory.research.language_market import target_locale


class VoiceGenerationAgent(Agent):
    """
    Generate multilingual, scene-aware voice artifacts.

    If the provider supports generate_for_segment(), use the Voice Director.
    Otherwise fall back to the old provider API.
    """

    def __init__(
        self,
        voice_provider: VoiceProvider,
        output_root: str = "artifacts",
    ) -> None:
        self._voice_provider = voice_provider
        self._output_root = Path(output_root)

    @property
    def name(self) -> str:
        return "Voice Generation Agent"

    async def execute(
        self,
        state: WorkflowState,
    ) -> WorkflowState:
        if state.production_plan is None:
            raise ValueError(
                "Content production plan is required.",
            )

        if not state.production_approved:
            raise ValueError(
                "Production plan must be approved before voice generation.",
            )

        output_dir = artifact_subdir(
            state,
            "audio",
            self._output_root,
        )

        segments = state.production_plan.voice_segments
        total_segments = len(segments)

        audience = (
            state.strategy.audience
            if state.strategy is not None
            else ""
        )
        topic = state.topic or ""

        target_language = str(
            state.metadata.get(
                "target_language",
                "",
            )
            or ""
        ).strip().lower()

        target_language_name = str(
            state.metadata.get(
                "target_language_name",
                "",
            )
            or ""
        ).strip()

        target_market_geo = str(
            state.metadata.get(
                "target_market_geo",
                "",
            )
            or ""
        ).strip().upper()

        resolved_locale = str(
            state.metadata.get(
                "target_locale",
                "",
            )
            or ""
        ).strip()

        if (
            not resolved_locale
            and target_language
        ):
            resolved_locale = target_locale(
                target_language,
                target_market_geo,
            )
            state.metadata[
                "target_locale"
            ] = resolved_locale

        voice_audience = audience

        if target_language_name:
            voice_audience = (
                f"Target narration language: "
                f"{target_language_name}. "
                + (
                    f"Target locale: {resolved_locale}. "
                    if resolved_locale
                    else ""
                )
                + audience
            )

            print(
                "[VOICE TARGET] "
                f"language={target_language}/"
                f"{target_language_name}, "
                f"locale={resolved_locale or '-'}, "
                f"market={target_market_geo or '-'}"
            )

        artifacts: list[VoiceArtifact] = []
        manifest: list[dict[str, Any]] = []

        profiled_generate = getattr(
            self._voice_provider,
            "generate_for_segment",
            None,
        )

        for index, segment in enumerate(
            segments,
            start=1,
        ):
            output_path = (
                output_dir
                / f"segment_{segment.id}.wav"
            )

            if callable(profiled_generate):
                result = await profiled_generate(
                    text=segment.text,
                    output_path=str(output_path),
                    segment_index=index,
                    total_segments=total_segments,
                    audience=voice_audience,
                    topic=topic,
                )

                duration = int(
                    result["duration_seconds"]
                )

                manifest.append(
                    {
                        "segment_id": segment.id,
                        "text": segment.text,
                        **result,
                    }
                )
            else:
                duration = await self._voice_provider.generate(
                    segment.text,
                    str(output_path),
                )
                manifest.append(
                    {
                        "segment_id": segment.id,
                        "text": segment.text,
                        "duration_seconds": duration,
                        "backend": "legacy",
                        "voice": "default",
                        "role": "narrator",
                        "style": "neutral",
                    }
                )

            artifacts.append(
                VoiceArtifact(
                    segment_id=segment.id,
                    file_path=str(output_path),
                    duration_seconds=duration,
                    provider="local",
                    status="generated",
                ),
            )

        (output_dir / "voice_manifest.json").write_text(
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        state.voice_generation = VoiceGenerationResult(
            artifacts=artifacts,
        )
        state.status = "voice_generated"

        print(f"[ARTIFACT] Audio: {output_dir}")
        print(
            f"[VOICE] Manifest: "
            f"{output_dir / 'voice_manifest.json'}"
        )

        return state
