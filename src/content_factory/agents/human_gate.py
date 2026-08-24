from content_factory.agents.base import Agent
from content_factory.human.approval import HumanApprovalService
from content_factory.orchestration.state import WorkflowState


class HumanApprovalGate(Agent):
    """Approve or reject the generated content strategy."""

    def __init__(
        self,
        approval_service: HumanApprovalService,
    ) -> None:
        self._approval_service = approval_service

    @property
    def name(self) -> str:
        return "Human Approval Gate"

    async def execute(
        self,
        state: WorkflowState,
    ) -> WorkflowState:
        """Request approval for the proposed content strategy."""

        if state.strategy is None:
            raise ValueError("Content strategy is required.")

        strategy = state.strategy

        message = (
            f"Topic: {strategy.topic}\n"
            f"Audience: {strategy.audience}\n"
            f"Angle: {strategy.angle}\n"
            f"Hook: {strategy.hook}\n"
            f"Duration: {strategy.estimated_duration_minutes} minutes"
        )

        approved = await self._approval_service.request_approval(
            message,
        )

        # Keep generic approval state for compatibility.
        state.human_approved = approved

        # This is the field ScriptWriterAgent actually checks.
        state.strategy_approved = approved

        if approved:
            state.status = "strategy_approved"
            print("[APPROVAL] Strategy approved")
        else:
            state.status = "strategy_rejected"
            state.stop_requested = True
            print("[APPROVAL] Strategy rejected")

        return state
