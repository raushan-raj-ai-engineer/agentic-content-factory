from content_factory.agents.base import Agent
from content_factory.human.approval import HumanApprovalService
from content_factory.orchestration.state import WorkflowState


class FactCheckGate(Agent):
    """Stop the workflow when fact checking fails or is rejected."""

    def __init__(self, approval_service: HumanApprovalService) -> None:
        self._approval_service = approval_service

    @property
    def name(self) -> str:
        return "Fact Check Gate"

    async def execute(self, state: WorkflowState) -> WorkflowState:
        if state.fact_check is None:
            raise ValueError("Fact check result is required.")

        # If the automated fact checker rejects the script, require a decision.
        # If it passes, continue without a redundant prompt.
        if state.fact_check.approved:
            state.status = "fact_check_approved"
            return state

        issues = "\n".join(str(item) for item in state.fact_check.issues)
        message = (
            "Automated fact check did not approve the script.\n\n"
            f"Score: {state.fact_check.score}\n"
            f"Issues:\n{issues or 'No details provided.'}\n\n"
            "Continue anyway?"
        )

        approved = await self._approval_service.request_approval(message)

        if not approved:
            state.stop_requested = True
            state.status = "fact_check_rejected"
        else:
            state.status = "fact_check_overridden"

        return state
