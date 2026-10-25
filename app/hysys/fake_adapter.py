import json
import platform
from pathlib import Path

from app.domain.models import SimulationResult, SimulationSpec
from app.hysys.interface import EventSink, HysysCapabilities, HysysSessionInfo
from app.runs.models import RunEvent, RunState


class FakeHysysAdapter:
    """Deterministic contract-test adapter that must never serve production."""

    def __init__(self, *, production_mode: bool = False) -> None:
        if production_mode:
            raise ValueError("fake HYSYS adapter is forbidden in production")
        self.owned_by_app = False

    def probe(self) -> HysysCapabilities:
        return HysysCapabilities(
            python_architecture=platform.architecture()[0],
            progid="fake",
            architecture_compatible=True,
            progid_configured=True,
            dispatch=True,
            version_read=True,
            blank_case=True,
            stream_round_trip=True,
            case_save=True,
            hysys_version="fake",
        )

    def start_owned_session(self) -> HysysSessionInfo:
        self.owned_by_app = True
        return HysysSessionInfo(progid="fake", owned_by_app=True, version="fake")

    def build_and_run(
        self,
        spec: SimulationSpec,
        run_dir: Path,
        event_sink: EventSink,
    ) -> SimulationResult:
        run_dir = Path(run_dir).resolve()
        run_dir.mkdir(parents=True, exist_ok=True)
        stages = (
            (RunState.CONNECTING, "fake session connected"),
            (RunState.BUILDING_CASE, "fake case built"),
            (RunState.SOLVING, "fake solver completed"),
            (RunState.READING_RESULTS, "fake results read"),
            (RunState.VALIDATING, "fake results validated"),
        )
        for state, message in stages:
            event_sink(RunEvent(state=state, message=message))

        case_path = (run_dir / "fake-case.hsc").resolve()
        if not case_path.is_relative_to(run_dir):
            raise ValueError("artifact path escapes run directory")
        case_path.write_text(
            json.dumps({"title": spec.title, "source": "fake"}, ensure_ascii=False),
            encoding="utf-8",
        )
        return SimulationResult(
            run_id=run_dir.name,
            source="fake",
            converged=True,
            hysys_version="fake",
            case_paths=[str(case_path)],
            warnings=["test-only fake HYSYS result"],
        )

    def close_owned_session(self) -> None:
        self.owned_by_app = False
