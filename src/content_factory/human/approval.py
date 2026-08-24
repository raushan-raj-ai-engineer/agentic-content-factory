from abc import ABC, abstractmethod


class HumanApprovalService(ABC):
    """Human-in-the-loop approval service."""

    @abstractmethod
    async def request_approval(
        self,
        message: str,
    ) -> bool:
        """Request a human approval decision."""
        ...


class CLIApprovalService(HumanApprovalService):
    """Approval service supporting auto, manual, and skip modes."""

    def __init__(
        self,
        *,
        mode: str = "manual",
        response: str = "y",
    ) -> None:
        self._mode = mode.strip().lower()
        self._response = response.strip().lower()

        if self._mode not in {"auto", "manual", "skip"}:
            raise ValueError(
                f"Unsupported approval mode: {mode}. "
                "Expected auto, manual, or skip.",
            )

        if self._mode == "auto" and self._response not in {"y", "yes", "n", "no"}:
            raise ValueError(
                "Auto approval response must be y/yes or n/no.",
            )

    async def request_approval(
        self,
        message: str,
    ) -> bool:
        print()
        print("=" * 60)
        print("HUMAN APPROVAL")
        print("=" * 60)
        print(message)
        print()

        if self._mode == "skip":
            print("[APPROVAL] SKIPPED -> CONTINUE")
            return True

        if self._mode == "auto":
            approved = self._response in {"y", "yes"}
            print(f"[AUTO APPROVAL] -> {'Y' if approved else 'N'}")
            return approved

        while True:
            response = input("Approve? [y/n]: ").strip().lower()
            if response in {"y", "yes"}:
                return True
            if response in {"n", "no"}:
                return False
            print("Please enter y or n.")
