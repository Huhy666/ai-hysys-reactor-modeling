import asyncio
from pathlib import Path

from app.hysys.com_worker import ComWorker
from app.hysys.interface import HysysAdapter
from app.runs.models import CancellationCheck, EventSink, RunRecord


class HysysRunExecutor:
    """Bridge async run jobs to one application-owned HYSYS STA thread."""

    def __init__(
        self,
        adapter: HysysAdapter,
        artifact_root: Path,
        *,
        com_worker: ComWorker | None = None,
    ) -> None:
        self.adapter = adapter
        self.artifact_root = Path(artifact_root).resolve()
        self.com_worker = com_worker or ComWorker()
        self._started = False
        self._session_started = False

    async def start(self) -> None:
        if self._started:
            return
        self.com_worker.start()
        self._started = True

    async def stop(self) -> None:
        if not self._started:
            return
        await asyncio.wrap_future(
            self.com_worker.submit(self.adapter.close_owned_session)
        )
        await asyncio.to_thread(self.com_worker.stop)
        self._session_started = False
        self._started = False

    async def execute(
        self,
        run: RunRecord,
        event_sink: EventSink,
        cancellation_requested: CancellationCheck,
    ):
        if cancellation_requested():
            return None
        if not self._started:
            raise RuntimeError("HYSYS COM worker is not running")

        run_dir = (self.artifact_root / run.id).resolve()
        if not run_dir.is_relative_to(self.artifact_root):
            raise ValueError("run directory escapes HYSYS artifact root")
        run_dir.mkdir(parents=True, exist_ok=True)
        loop = asyncio.get_running_loop()

        def forward_event(event) -> None:
            future = asyncio.run_coroutine_threadsafe(
                event_sink(event.state, event.message, event.data),
                loop,
            )
            future.result()

        def execute_on_sta():
            if not self._session_started:
                self.adapter.start_owned_session()
                self._session_started = True
            return self.adapter.build_and_run(run.spec, run_dir, forward_event)

        return await asyncio.wrap_future(self.com_worker.submit(execute_on_sta))
