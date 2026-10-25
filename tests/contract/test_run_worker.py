import asyncio

import pytest

from app.domain.models import ReactorDecision, ReactorType, SimulationResult
from app.runs.models import RunState
from app.runs.repository import FileRunRepository
from app.runs.service import RunService
from app.runs.worker import RunWorker
from tests.unit.test_run_repository import _spec


def _decision():
    return ReactorDecision(
        reactor_type=ReactorType.CONVERSION,
        reason_codes=["KNOWN_CONVERSION"],
        explanation="known conversion",
    )


class SerialExecutor:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.calls: list[str] = []

    async def execute(self, run, event_sink, cancellation_requested):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.calls.append(run.id)
        await event_sink(RunState.SOLVING, "solving")
        await asyncio.sleep(0)
        self.active -= 1
        return SimulationResult(run_id=run.id, source="fake", converged=True)


class SafeBoundaryExecutor:
    def __init__(self) -> None:
        self.solving = asyncio.Event()
        self.release_boundary = asyncio.Event()
        self.saw_cancel_at_boundary = False

    async def execute(self, run, event_sink, cancellation_requested):
        await event_sink(RunState.SOLVING, "solver owns the case")
        self.solving.set()
        await self.release_boundary.wait()
        self.saw_cancel_at_boundary = cancellation_requested()
        return None


@pytest.mark.asyncio
async def test_worker_serializes_simultaneous_runs(tmp_path):
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    repository = FileRunRepository(tmp_path)
    service = RunService(repository, queue)
    executor = SerialExecutor()
    worker = RunWorker(repository, queue, executor)
    for run_id in ("first", "second"):
        service.create_run(_spec(), _decision(), run_id=run_id)
        service.enqueue(run_id)

    await worker.start()
    await queue.join()
    await worker.stop()

    assert executor.calls == ["first", "second"]
    assert executor.max_active == 1
    assert repository.get("first").state is RunState.SUCCEEDED
    assert repository.get("second").state is RunState.SUCCEEDED


@pytest.mark.asyncio
async def test_cancelled_queued_run_never_reaches_executor(tmp_path):
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    repository = FileRunRepository(tmp_path)
    service = RunService(repository, queue)
    executor = SerialExecutor()
    worker = RunWorker(repository, queue, executor)
    service.create_run(_spec(), _decision(), run_id="cancelled")
    service.enqueue("cancelled")
    service.cancel("cancelled")

    await worker.start()
    await queue.join()
    await worker.stop()

    assert executor.calls == []
    assert repository.get("cancelled").state is RunState.CANCELLED


@pytest.mark.asyncio
async def test_running_cancel_stops_at_executor_safe_boundary(tmp_path):
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    repository = FileRunRepository(tmp_path)
    service = RunService(repository, queue)
    executor = SafeBoundaryExecutor()
    worker = RunWorker(repository, queue, executor)
    service.create_run(_spec(), _decision(), run_id="running")
    service.enqueue("running")

    await worker.start()
    await executor.solving.wait()
    cancel_requested = service.cancel("running")

    assert cancel_requested.state is RunState.SOLVING
    assert cancel_requested.cancel_requested is True

    executor.release_boundary.set()
    await queue.join()
    await worker.stop()

    assert executor.saw_cancel_at_boundary is True
    assert repository.get("running").state is RunState.CANCELLED

