from content_factory.agents.base import Agent
from content_factory.human.approval import HumanApprovalService
from content_factory.orchestration.state import WorkflowState


class ScriptApprovalGate(Agent):
    """Approve or reject the generated script."""

    def __init__(self, approval_service: HumanApprovalService) -> None:
        self._approval_service = approval_service

    @property
    def name(self) -> str:
        return "Script Approval Gate"

    async def execute(self, state: WorkflowState) -> WorkflowState:
        if state.script is None:
            raise ValueError("YouTube script is required before approval.")

        sections = "\n\n".join(
            f"{index}. {section.title}\n{section.content}"
            for index, section in enumerate(state.script.sections, start=1)
        )

        message = (
            "SCRIPT APPROVAL REQUIRED\n\n"
            f"Title: {state.script.title}\n\n"
            f"HOOK:\n{state.script.hook}\n\n"
            f"INTRODUCTION:\n{state.script.introduction}\n\n"
            f"SECTIONS:\n{sections}\n\n"
            f"CONCLUSION:\n{state.script.conclusion}\n\n"
            f"CALL TO ACTION:\n{state.script.call_to_action}\n\n"
            f"Duration: {state.script.estimated_duration_minutes} minutes"
        )

        approved = await self._approval_service.request_approval(message)
        state.script_approved = approved

        if not approved:
            state.stop_requested = True
            state.status = "script_rejected"
        else:
            state.status = "script_approved"

        return state
