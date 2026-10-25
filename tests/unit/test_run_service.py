import asyncio

from app.domain.models import ReactorDecision, ReactorType
from app.runs.models import RunState
from app.runs.repository import FileRunRepository
from app.runs.service import RunService
from tests.unit.test_run_repository import _spec


def _decision(*, blocked: bool = False):
    return ReactorDecision(
        reactor_type=ReactorType.CONVERSION,
        reason_codes=["KNOWN_CONVERSION"],
        explanation="known conversion",
        blocking_issues=(
            [
                {
                    "code": "MISSING_FEED",
                    "field": "feeds",
                    "severity": "blocking",
                    "message": "feed is required",
                }
            ]
            if blocked
            else []
        ),
    )


def test_create_run_is_ready_unless_decision_needs_clarification(tmp_path):
    service = RunService(FileRunRepository(tmp_path), asyncio.Queue())

    ready = service.create_run(_spec(), _decision(), run_id="ready")
    blocked = service.create_run(_spec(), _decision(blocked=True), run_id="blocked")

    assert ready.state is RunState.READY
    assert blocked.state is RunState.NEEDS_CLARIFICATION


def test_enqueue_transitions_ready_run_and_records_event(tmp_path):
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    repository = FileRunRepository(tmp_path)
    service = RunService(repository, queue)
    service.create_run(_spec(), _decision(), run_id="ready")

    queued = service.enqueue("ready")

    assert queued.state is RunState.QUEUED
    assert queue.get_nowait() == "ready"
    events = (tmp_path / "ready" / "events.jsonl").read_text(encoding="utf-8")
    assert '"state":"queued"' in events


def test_ready_and_queued_runs_cancel_immediately(tmp_path):
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    service = RunService(FileRunRepository(tmp_path), queue)
    service.create_run(_spec(), _decision(), run_id="ready")
    service.create_run(_spec(), _decision(), run_id="queued")
    service.enqueue("queued")

    ready = service.cancel("ready")
    queued = service.cancel("queued")

    assert ready.state is RunState.CANCELLED
    assert queued.state is RunState.CANCELLED
    assert ready.cancel_requested is False
    assert queued.cancel_requested is False


def test_running_cancel_only_sets_request_flag(tmp_path):
    repository = FileRunRepository(tmp_path)
    service = RunService(repository, asyncio.Queue())
    service.create_run(_spec(), _decision(), run_id="running")
    repository.update_state("running", RunState.SOLVING)

    record = service.cancel("running")

    assert record.state is RunState.SOLVING
    assert record.cancel_requested is True

