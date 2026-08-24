from collections.abc import Sequence

from content_factory.agents.base import Agent
from content_factory.orchestration.state import WorkflowState
from content_factory.performance.profiler import PerformanceProfiler


class SequentialWorkflow:
    """Execute agents sequentially against shared workflow state."""

    def __init__(self, agents: Sequence[Agent]) -> None:
        self._agents = list(agents)

    async def run(
        self,
        state: WorkflowState,
    ) -> WorkflowState:
        """Execute every configured agent in sequence with performance profiling."""
        profiler = PerformanceProfiler()

        try:
            for agent in self._agents:
                if state.stop_requested:
                    print("[STOP]  Workflow stopped.")
                    break

                print(f"[START] {agent.name}")
                started = profiler.begin()

                try:
                    state = await agent.execute(state)
                except Exception as exc:
                    profiler.end(
                        agent=agent.name,
                        started=started,
                        status="failed",
                        error=f"{exc.__class__.__name__}: {exc}",
                    )
                    print(
                        f"[PERF] {agent.name}: "
                        f"{profiler._records[-1].elapsed_seconds:.1f}s (failed)"
                    )
                    raise
                else:
                    profiler.end(
                        agent=agent.name,
                        started=started,
                        status="done",
                    )
                    print(
                        f"[DONE]  {agent.name}"
                    )
                    print(
                        f"[PERF] {agent.name}: "
                        f"{profiler._records[-1].elapsed_seconds:.1f}s"
                    )

            if not state.stop_requested:
                state.status = "completed"

            return state

        finally:
            # A performance report is useful even for failed/stopped runs.
            try:
                profiler.print_summary(state)
            except Exception as exc:
                print(
                    f"[PERF] Report write skipped: "
                    f"{exc.__class__.__name__}"
                )
