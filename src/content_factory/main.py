import argparse
import asyncio
import importlib.util
import os
from uuid import uuid4

from content_factory.agents.content_producer import ContentProductionAgent
from content_factory.agents.authenticity_review import AuthenticityReviewAgent
from content_factory.agents.content_strategist import ContentStrategistAgent
from content_factory.agents.strategy_grounding import StrategyGroundingAgent
from content_factory.agents.study_localization import StudyLocalizationAgent
from content_factory.agents.study_animation_director import StudyAnimationDirectorAgent
from content_factory.agents.growth_strategy import GrowthStrategyAgent
from content_factory.agents.fact_check_gate import FactCheckGate
from content_factory.agents.fact_checker import FactCheckerAgent
from content_factory.agents.human_gate import HumanApprovalGate
from content_factory.agents.model_memory_release import ModelMemoryReleaseAgent
from content_factory.agents.monetization_safety import MonetizationSafetyAgent
from content_factory.agents.production_approval_gate import ProductionApprovalGate
from content_factory.agents.research_planner import ResearchPlannerAgent
from content_factory.agents.script_approval_gate import ScriptApprovalGate
from content_factory.agents.script_reviewer import ScriptReviewerAgent
from content_factory.agents.packaging_optimizer import PackagingOptimizerAgent
from content_factory.agents.script_writer import ScriptWriterAgent
from content_factory.agents.retention_optimizer import RetentionOptimizerAgent
from content_factory.agents.thumbnail_generator import ThumbnailGenerationAgent
from content_factory.agents.growth_readiness import GrowthReadinessAgent
from content_factory.agents.trend_researcher import TrendResearchAgent
from content_factory.agents.evidence_enricher import EvidenceEnrichmentAgent
from content_factory.agents.video_assembler import VideoAssemblyAgent
from content_factory.agents.visual_generator import VisualGenerationAgent
from content_factory.agents.voice_generator import VoiceGenerationAgent
from content_factory.config.settings import Settings
from content_factory.human.approval import CLIApprovalService
from content_factory.llm.factory import select_llm_provider
from content_factory.modes import infer_content_mode
from content_factory.orchestration.state import WorkflowState
from content_factory.orchestration.workflow import SequentialWorkflow
from content_factory.result_reporting import (
    print_compact_result,
    write_workflow_result,
)
from content_factory.research.factory import create_research_service
from content_factory.thumbnail.local import LocalThumbnailGenerator
from content_factory.video.local import LocalVideoAssembler
from content_factory.visual.local import LocalVisualProvider
from content_factory.voice.local import LocalVoiceProvider


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="content-factory")
    parser.add_argument("--config", default="configs/local.yaml")
    parser.add_argument("--topic", help="Research this exact topic.")
    parser.add_argument(
        "--category",
        choices=[
            "technical",
            "ai",
            "software_testing",
            "funny",
            "entertainment",
            "general",
            "auto",
        ],
        help="Let the agent discover a topic in this category.",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Fully automatic cross-category topic discovery.",
    )
    parser.add_argument(
        "--llm-provider",
        choices=["auto", "ollama", "gemini", "openai", "anthropic", "compatible"],
        help=(
            "LLM provider for the entire run. Overrides LLM_PROVIDER. "
            "Once selected, the same provider/model is used by every agent."
        ),
    )
    parser.add_argument(
        "--llm-model",
        help=(
            "Model override for the selected provider. The model is locked for "
            "the entire run."
        ),
    )
    parser.add_argument(
        "--locale",
        help=(
            "Narration locale such as en-US, en-GB, or hi-IN. "
            "Study Mode defaults to en-US."
        ),
    )
    parser.add_argument(
        "--duration-minutes",
        type=int,
        help=(
            "Study-video duration preference in minutes. Overrides the strategist "
            "for this run. If omitted, STUDY_DURATION_MINUTES is used when set; "
            "otherwise the approved strategy duration is followed."
        ),
    )
    parser.add_argument(
        "--voice-backend",
        choices=["auto", "kokoro", "piper", "macos"],
        help=(
            "Narration backend. Study Mode defaults to auto, which prefers local "
            "Kokoro when installed and falls back to Piper/macOS."
        ),
    )
    parser.add_argument(
        "--voice-profile",
        choices=["us-male-warm", "us-female-clear", "auto"],
        help=(
            "Narrator profile. Study Mode defaults to us-male-warm. "
            "Use auto to select any matching local voice."
        ),
    )
    parser.add_argument(
        "--voice",
        help=(
            "Exact installed Kokoro/Piper/macOS voice, e.g. am_michael, "
            "af_bella, en_US-ryan-medium, or Alex."
        ),
    )
    parser.add_argument(
        "--list-voices",
        action="store_true",
        help="List installed Piper/macOS voices and exit.",
    )
    parser.add_argument(
        "--verbose-result",
        action="store_true",
        help=(
            "Print the full strategy/script/production JSON after the compact "
            "summary. By default full details are saved to workflow_result.json."
        ),
    )
    return parser.parse_args()


async def run() -> None:
    args = parse_args()
    settings = Settings.from_yaml(args.config)

    if args.topic:
        settings.trend_mode = "topic"
        settings.trend_topic = args.topic
    elif args.auto:
        settings.trend_mode = "auto"
        settings.trend_category = "auto"
    elif args.category:
        settings.trend_mode = "auto"
        settings.trend_category = args.category

    content_mode = infer_content_mode(
        category=args.category,
        topic=args.topic,
    )

    if content_mode == "study" and not importlib.util.find_spec("manim"):
        raise RuntimeError(
            "Study Mode now requires semantic Manim rendering. "
            "Run: brew install cairo pkg-config ffmpeg && "
            "bash setup_channel.sh --manim. "
            "Static PNG/zoom fallback is intentionally disabled."
        )

    research_service = create_research_service(settings)

    approval_service = CLIApprovalService(
        mode=settings.approval_mode,
        response=settings.approval_response,
    )
    selected_locale = args.locale or ("en-US" if content_mode == "study" else None)
    locale_key = (selected_locale or "").strip().lower().replace("_", "-")
    selected_voice_profile = args.voice_profile or (
        "us-male-warm"
        if content_mode == "study" and locale_key in {"", "en-us"}
        else "auto"
    )
    selected_voice_backend = (
        args.voice_backend
        or os.getenv("CONTENT_FACTORY_STUDY_VOICE_BACKEND", "auto")
    ).strip().lower()
    if selected_voice_backend not in {"auto", "kokoro", "piper", "macos"}:
        raise ValueError(
            "CONTENT_FACTORY_STUDY_VOICE_BACKEND must be one of: "
            "auto, kokoro, piper, macos"
        )
    voice_provider = LocalVoiceProvider(
        language=selected_locale,
        voice_profile=selected_voice_profile,
        preferred_voice=args.voice,
        preferred_backend=selected_voice_backend,
    )

    if args.list_voices:
        inventory = voice_provider.inventory()
        print("\nKokoro voices:")
        for item in inventory.get("kokoro", []):
            marker = " (default)" if item.get("default") else ""
            print(f"  {item['key']}  ({item['locale']}){marker}")
        print("\nPiper voices:")
        for item in inventory.get("piper", []):
            print(f"  {item['key']}  ({item['locale']})")
        print("\nmacOS voices:")
        for item in inventory.get("macos", []):
            print(f"  {item['name']}  ({item['locale']})")
        print(
            "\nStudy defaults: locale=en-US, "
            "voice-profile=us-male-warm"
        )
        return

    llm_selection = await select_llm_provider(
        settings,
        provider_override=args.llm_provider,
        model_override=args.llm_model,
    )
    llm = llm_selection.provider
    if llm_selection.fallback_from:
        print(
            "[LLM FALLBACK] "
            f"requested={llm_selection.fallback_from}, "
            f"fallback=ollama, model={llm_selection.model_name}; "
            f"reason={llm_selection.fallback_reason}"
        )
    print(
        "[LLM LOCK] "
        f"provider={llm_selection.provider_name}, "
        f"model={llm_selection.model_name}, "
        f"selection={llm_selection.selection_mode}; "
        "primary locked; retryable cloud failures may switch once to Ollama when enabled."
    )

    visual_provider = LocalVisualProvider()
    video_assembler = LocalVideoAssembler()
    thumbnail_generator = LocalThumbnailGenerator()

    workflow = SequentialWorkflow(
        agents=[
            ResearchPlannerAgent(
                llm,
                mode=settings.trend_mode,
                topic=settings.trend_topic,
                category=settings.trend_category,
            ),
            TrendResearchAgent(
                research_service,
                lookback_days=settings.trend_lookback_days,
            ),
            StudyLocalizationAgent(),
            EvidenceEnrichmentAgent(),
            ContentStrategistAgent(llm),
            StrategyGroundingAgent(),
            GrowthStrategyAgent(llm),
            HumanApprovalGate(approval_service),
            ScriptWriterAgent(llm),
            AuthenticityReviewAgent(llm),
            RetentionOptimizerAgent(llm),
            PackagingOptimizerAgent(llm),
            ScriptReviewerAgent(llm),
            FactCheckerAgent(llm),
            FactCheckGate(approval_service),
            ScriptApprovalGate(approval_service),
            ContentProductionAgent(llm),
            StudyAnimationDirectorAgent(llm),
            ProductionApprovalGate(approval_service),
            ModelMemoryReleaseAgent(llm),
            VoiceGenerationAgent(voice_provider),
            VisualGenerationAgent(visual_provider),
            VideoAssemblyAgent(video_assembler),
            ThumbnailGenerationAgent(thumbnail_generator),
            GrowthReadinessAgent(),
            MonetizationSafetyAgent(),
        ],
    )

    state = WorkflowState(run_id=str(uuid4()))
    requested_duration = args.duration_minutes
    if requested_duration is None and content_mode == "study":
        raw_duration = os.getenv("STUDY_DURATION_MINUTES", "").strip()
        if raw_duration:
            try:
                requested_duration = int(raw_duration)
            except ValueError as exc:
                raise ValueError("STUDY_DURATION_MINUTES must be a positive integer") from exc
    if requested_duration is not None and requested_duration <= 0:
        raise ValueError("--duration-minutes/STUDY_DURATION_MINUTES must be > 0")

    state.metadata["requested_category"] = (
        args.category
        or ("auto" if args.auto else "")
    )
    state.metadata["explicit_topic"] = bool(args.topic)
    state.metadata["content_mode"] = content_mode
    state.metadata["requested_locale"] = args.locale or ""
    state.metadata["voice_profile"] = selected_voice_profile
    state.metadata["preferred_voice"] = args.voice or ""
    state.metadata["voice_backend_preference"] = selected_voice_backend
    state.metadata["requested_duration_minutes"] = requested_duration or 0
    state.metadata["llm_requested_provider"] = llm_selection.requested_provider
    state.metadata["llm_provider"] = llm_selection.provider_name
    state.metadata["llm_model"] = llm_selection.model_name
    state.metadata["llm_selection_mode"] = llm_selection.selection_mode
    state.metadata["llm_locked_for_run"] = True
    print(f"[MODE] Content mode: {state.metadata['content_mode']}")
    if content_mode == "study":
        print(
            "[STUDY DEFAULTS] "
            f"locale={selected_locale or 'en-US'}, "
            f"voice_profile={selected_voice_profile}, "
            f"backend={selected_voice_backend}, "
            f"voice={args.voice or 'profile-selected'}, "
            f"duration={'user:'+str(requested_duration)+'m' if requested_duration else 'strategy'}"
        )
    result = await workflow.run(state)

    result_path = write_workflow_result(result)
    print_compact_result(result, result_path=result_path)

    if args.verbose_result:
        if result.research is not None:
            print("\nTop Trend Candidate:")
            print(result.research.top_candidate.model_dump_json(indent=2))

        if result.strategy is not None:
            print("\nGenerated Strategy:")
            print(result.strategy.model_dump_json(indent=2))

        if result.script is not None:
            print("\nGenerated Script:")
            print(result.script.model_dump_json(indent=2))

        if result.script_review is not None:
            print("\nScript Review:")
            print(result.script_review.model_dump_json(indent=2))

        if result.fact_check is not None:
            print("\nFact Check:")
            print(result.fact_check.model_dump_json(indent=2))

        if result.production_plan is not None:
            print("\nContent Production Plan:")
            print(result.production_plan.model_dump_json(indent=2))

        if result.video_assembly is not None:
            print("\nVideo Assembly:")
            print(result.video_assembly.model_dump_json(indent=2))

        if result.thumbnail_generation is not None:
            print("\nThumbnail Generation:")
            print(result.thumbnail_generation.model_dump_json(indent=2))



def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
