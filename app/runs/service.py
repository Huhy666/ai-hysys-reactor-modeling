import asyncio

from app.domain.models import ReactorDecision, SimulationSpec
from app.runs.models import RunEvent, RunRecord, RunState
from app.runs.repository import FileRunRepository

_RUNNING_STATES = {
    RunState.CONNECTING,
    RunState.BUILDING_CASE,
    RunState.SOLVING,
    RunState.READING_RESULTS,
    RunState.VALIDATING,
}


class RunService:
    def __init__(
        self,
        repository: FileRunRepository,
        queue: asyncio.Queue[str | None],
    ) -> None:
        self.repository = repository
        self.queue = queue

    def create_run(
        self,
        spec: SimulationSpec,
        decision: ReactorDecision,
        *,
        run_id: str | None = None,
        original_request: dict[str, object] | None = None,
    ) -> RunRecord:
        initial_state = (
            RunState.NEEDS_CLARIFICATION
            if decision.blocking_issues
            else RunState.READY
        )
        return self.repository.create(
            spec,
            decision,
            run_id=run_id,
            original_request=original_request,
            initial_state=initial_state,
        )

    def enqueue(self, run_id: str) -> RunRecord:
        record = self.repository.get(run_id)
        if record.state is not RunState.READY:
            raise ValueError(f"run {run_id} is not ready")
        record = self.repository.update_state(run_id, RunState.QUEUED)
        self.repository.append_event(
            run_id,
            RunEvent(state=RunState.QUEUED, message="run queued"),
        )
        self.queue.put_nowait(run_id)
        return record

    def cancel(self, run_id: str) -> RunRecord:
        record = self.repository.get(run_id)
        if record.state in {RunState.READY, RunState.QUEUED}:
            record = self.repository.update_state(run_id, RunState.CANCELLED)
            self.repository.append_event(
                run_id,
                RunEvent(state=RunState.CANCELLED, message="run cancelled"),
            )
            return record
        if record.state in _RUNNING_STATES:
            record = self.repository.update_state(
                run_id,
                record.state,
                cancel_requested=True,
            )
            self.repository.append_event(
                run_id,
                RunEvent(
                    state=record.state,
                    message="cancellation requested; waiting for safe boundary",
                ),
            )
        return record

    def get(self, run_id: str) -> RunRecord:
        return self.repository.get(run_id)

    def list_runs(self) -> list[RunRecord]:
        return self.repository.list()
