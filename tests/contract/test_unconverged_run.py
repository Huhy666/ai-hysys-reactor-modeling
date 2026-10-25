import asyncio

import pytest

from app.domain.models import SimulationResult
from app.runs.models import RunState
from app.runs.repository import FileRunRepository
from app.runs.service import RunService
from app.runs.worker import RunWorker
from tests.unit.test_run_repository import _decision, _spec


class UnconvergedExecutor:
    async def execute(self, run, event_sink, cancellation_requested):
        return SimulationResult(run_id=run.id, source="hysys", converged=False)


@pytest.mark.asyncio
async def test_unconverged_result_is_never_published_as_success(tmp_path):
    queue = asyncio.Queue()
    repository = FileRunRepository(tmp_path)
    service = RunService(repository, queue)
    worker = RunWorker(repository, queue, UnconvergedExecutor())
    record = service.create_run(_spec(), _decision())
    service.enqueue(record.id)
    await worker.start()
    await queue.join()
    await worker.stop()
    assert repository.get(record.id).state is RunState.FAILED
    assert not (tmp_path / record.id / "result.json").exists()
