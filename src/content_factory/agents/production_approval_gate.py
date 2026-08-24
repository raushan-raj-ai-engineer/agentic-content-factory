from content_factory.agents.base import Agent
from content_factory.human.approval import HumanApprovalService
from content_factory.orchestration.state import WorkflowState


class ProductionApprovalGate(Agent):
    """Approve or reject the production plan."""

    def __init__(self, approval_service: HumanApprovalService) -> None:
        self._approval_service = approval_service

    @property
    def name(self) -> str:
        return "Production Approval Gate"

    async def execute(self, state: WorkflowState) -> WorkflowState:
        if state.production_plan is None:
            raise ValueError("Production plan is required before approval.")

        plan = state.production_plan

        message = (
            f"Title: {plan.title}\n"
            f"Voice segments: {len(plan.voice_segments)}\n"
            f"Visual scenes: {len(plan.visual_scenes)}\n"
            f"Thumbnail: {plan.thumbnail_prompt}\n"
            f"YouTube tags: {', '.join(plan.youtube_tags)}"
        )

        approved = await self._approval_service.request_approval(message)
        state.production_approved = approved

        if not approved:
            state.stop_requested = True
            state.status = "production_rejected"
        else:
            state.status = "production_approved"

        return state
