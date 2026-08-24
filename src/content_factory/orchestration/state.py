from dataclasses import dataclass, field
from typing import Any

from content_factory.models.content import (
    ContentProductionPlan,
    ContentStrategy,
    FactCheckResult,
    ResearchPlan,
    ScriptReview,
    ThumbnailGenerationResult,
    TrendResearch,
    VideoAssemblyResult,
    VisualGenerationResult,
    VoiceGenerationResult,
    YouTubeScript,
)


@dataclass
class WorkflowState:
    """Shared state passed between sequential agents."""

    run_id: str

    topic: str | None = None
    research_plan: ResearchPlan | None = None
    research: TrendResearch | None = None
    strategy: ContentStrategy | None = None
    script: YouTubeScript | None = None
    fact_check: FactCheckResult | None = None
    script_review: ScriptReview | None = None
    production_plan: ContentProductionPlan | None = None
    thumbnail_generation: ThumbnailGenerationResult | None = None
    voice_generation: VoiceGenerationResult | None = None
    visual_generation: VisualGenerationResult | None = None
    video_assembly: VideoAssemblyResult | None = None

    strategy_approved: bool = False
    script_approved: bool = False
    production_approved: bool = False

    # human_approved: bool = False
    stop_requested: bool = False

    metadata: dict[str, Any] = field(default_factory=dict)

    status: str = "created"
