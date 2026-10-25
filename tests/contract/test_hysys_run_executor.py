import asyncio

import pytest

from app.config import Settings
from app.domain.models import ReactorDecision, ReactorType, SimulationResult
from app.hysys.com_worker import ComWorker
from app.hysys.executor import HysysRunExecutor
from app.hysys.interface import HysysSessionInfo
from app.main import create_app
from app.runs.repository import FileRunRepository
from tests.unit.test_run_repository import _spec


class FakePythonCom:
    COINIT_APARTMENTTHREADED = 2

    def CoInitializeEx(self, flag):
        assert flag == self.COINIT_APARTMENTTHREADED

    def CoUninitialize(self):
        return None


class RecordingAdapter:
    def __init__(self):
        self.calls = []

    def start_owned_session(self):
        self.calls.append("start")
        return HysysSessionInfo(
            progid="HYSYS.Application",
            owned_by_app=True,
            version="15",
        )

    def build_and_run(self, spec, run_dir, event_sink):
        self.calls.append(("build", run_dir.name, spec.title))
        from app.runs.models import RunEvent, RunState

        event_sink(RunEvent(state=RunState.SOLVING, message="HYSYS solving"))
        return SimulationResult(
            run_id=run_dir.name,
            source="hysys",
            converged=True,
            hysys_version="15",
        )

    def close_owned_session(self):
        self.calls.append("close")


@pytest.mark.asyncio
async def test_executor_starts_owned_hysys_on_first_run_and_bridges_events(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "app.hysys.com_worker._load_pythoncom", lambda: FakePythonCom()
    )
    repository = FileRunRepository(tmp_path)
    run = repository.create(
        _spec(),
        ReactorDecision(
            reactor_type=ReactorType.CONVERSION,
            reason_codes=["KNOWN_CONVERSION"],
            explanation="known conversion",
        ),
        run_id="background-run",
    )
    adapter = RecordingAdapter()
    executor = HysysRunExecutor(adapter, tmp_path, com_worker=ComWorker())
    events = []

    async def event_sink(state, message, data=None):
        events.append((state, message, data or {}))

    await executor.start()
    result = await executor.execute(run, event_sink, lambda: False)
    await executor.stop()

    assert result.source == "hysys"
    assert adapter.calls == [
        "start",
        ("build", "background-run", "repository test"),
        "close",
    ]
    assert [(state.value, message) for state, message, _ in events] == [
        ("solving", "HYSYS solving")
    ]


@pytest.mark.asyncio
async def test_executor_honors_cancellation_before_starting_hysys(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.hysys.com_worker._load_pythoncom", lambda: FakePythonCom()
    )
    repository = FileRunRepository(tmp_path)
    run = repository.create(
        _spec(),
        ReactorDecision(
            reactor_type=ReactorType.CONVERSION,
            reason_codes=["KNOWN_CONVERSION"],
            explanation="known conversion",
        ),
        run_id="cancelled-run",
    )
    adapter = RecordingAdapter()
    executor = HysysRunExecutor(adapter, tmp_path, com_worker=ComWorker())

    await executor.start()
    result = await executor.execute(run, lambda *args: asyncio.sleep(0), lambda: True)
    await executor.stop()

    assert result is None
    assert adapter.calls == ["close"]


def test_app_configures_background_hysys_executor_when_seed_exists(tmp_path):
    seed = tmp_path / "base-case.hsc"
    seed.write_bytes(b"seed")

    app = create_app(
        Settings(
            hysys_base_case_path=seed,
            hysys_artifact_dir=tmp_path / "runs",
            _env_file=None,
        )
    )

    assert isinstance(app.state.run_worker.executor, HysysRunExecutor)
