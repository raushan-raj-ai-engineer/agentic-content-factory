import argparse
import asyncio
from uuid import uuid4

from content_factory.agents.content_producer import ContentProductionAgent
from content_factory.agents.authenticity_review import AuthenticityReviewAgent
from content_factory.agents.content_strategist import ContentStrategistAgent
from content_factory.agents.strategy_grounding import StrategyGroundingAgent
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
from content_factory.llm.local import LocalLLMProvider
from content_factory.orchestration.state import WorkflowState
from content_factory.orchestration.workflow import SequentialWorkflow
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

    research_service = create_research_service(settings)

    llm = LocalLLMProvider(
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        timeout=settings.llm_timeout,
    )

    approval_service = CLIApprovalService(
        mode=settings.approval_mode,
        response=settings.approval_response,
    )
    voice_provider = LocalVoiceProvider()
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
    result = await workflow.run(state)

    print()
    print("=" * 60)
    print("WORKFLOW RESULT")
    print("=" * 60)
    print(f"Run ID: {result.run_id}")
    print(f"Topic: {result.topic}")
    print(f"Status: {result.status}")
    print(f"Strategy Approved: {result.strategy_approved}")
    print(f"Script Approved: {result.script_approved}")
    print(f"Production Approved: {result.production_approved}")

    if result.metadata.get("failed_agent"):
        print(f"Failed Agent: {result.metadata['failed_agent']}")
        print(f"Error: {result.metadata.get('error', '')}")

    if result.research is not None:
        print()
        print("Top Trend Candidate:")
        print(result.research.top_candidate.model_dump_json(indent=2))

    if result.strategy is not None:
        print()
        print("Generated Strategy:")
        print(result.strategy.model_dump_json(indent=2))

    if result.script is not None:
        print()
        print("Generated Script:")
        print(result.script.model_dump_json(indent=2))

    if result.script_review is not None:
        print()
        print("Script Review:")
        print(result.script_review.model_dump_json(indent=2))

    if result.fact_check is not None:
        print()
        print("Fact Check:")
        print(result.fact_check.model_dump_json(indent=2))

    if result.production_plan is not None:
        print()
        print("Content Production Plan:")
        print(result.production_plan.model_dump_json(indent=2))

    if result.video_assembly is not None:
        print()
        print("Video Assembly:")
        print(result.video_assembly.model_dump_json(indent=2))

    if result.thumbnail_generation is not None:
        print()
        print("Thumbnail Generation:")
        print(result.thumbnail_generation.model_dump_json(indent=2))


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
