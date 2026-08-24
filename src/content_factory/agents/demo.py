from pydantic import BaseModel, Field


class TrendCandidate(BaseModel):
    """A potential content topic discovered during research."""

    topic: str
    trend_score: int = Field(ge=0, le=100)
    audience_fit: int = Field(ge=0, le=100)
    competition: int = Field(ge=0, le=100)
    opportunity_score: int = 0


class TrendResearch(BaseModel):
    """Result produced by the trend research agent."""

    candidates: list[TrendCandidate]
    top_candidate: TrendCandidate


class ContentStrategy(BaseModel):
    """Structured strategy produced for a selected topic."""

    topic: str
    audience: str
    angle: str
    hook: str
    content_type: str
    estimated_duration_minutes: int = Field(
        ge=1,
        le=60,
    )
