import asyncio
from typing import Any

from app.runs.models import RunEvent, RunExecutor, RunState
from app.runs.repository import FileRunRepository


class RunWorker:
    def __init__(
        self,
        repository: FileRunRepository,
        queue: asyncio.Queue[str | None],
        executor: RunExecutor,
    ) -> None:
        self.repository = repository
        self.queue = queue
        self.executor = executor
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._consume())

    async def stop(self) -> None:
        if self._task is None:
            return
        await self.queue.put(None)
        await self._task
        self._task = None

    async def _consume(self) -> None:
        while True:
            run_id = await self.queue.get()
            try:
                if run_id is None:
                    return
                await self._execute(run_id)
            finally:
                self.queue.task_done()

    async def _execute(self, run_id: str) -> None:
        record = self.repository.get(run_id)
        if record.state is not RunState.QUEUED:
            return

        await self._record_event(run_id, RunState.CONNECTING, "starting run")

        async def event_sink(
            state: RunState,
            message: str,
            data: dict[str, Any] | None = None,
        ) -> None:
            await self._record_event(run_id, state, message, data)

        def cancellation_requested() -> bool:
            return self.repository.get(run_id).cancel_requested

        try:
            result = await self.executor.execute(
                self.repository.get(run_id),
                event_sink,
                cancellation_requested,
            )
            current = self.repository.get(run_id)
            if current.cancel_requested:
                await self._record_event(
                    run_id,
                    RunState.CANCELLED,
                    "run cancelled at safe boundary",
                )
            elif result is None:
                await self._record_event(
                    run_id,
                    RunState.FAILED,
                    "runner returned no result",
                )
            else:
                if not result.converged:
                    raise ValueError("HYSYS did not converge; result cannot be marked successful")
                self.repository.save_result(run_id, result)
                await self._record_event(run_id, RunState.SUCCEEDED, "run succeeded")
        except Exception as exc:
            self.repository.update_state(
                run_id,
                RunState.FAILED,
                error=f"{type(exc).__name__}: {exc}",
            )
            self.repository.append_event(
                run_id,
                RunEvent(state=RunState.FAILED, message="run failed"),
            )

    async def _record_event(
        self,
        run_id: str,
        state: RunState,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        self.repository.update_state(run_id, state)
        self.repository.append_event(
            run_id,
            RunEvent(state=state, message=message, data=data or {}),
        )
