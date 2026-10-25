"""Exercise web API -> real builders with recording boundaries, not real HYSYS."""

import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.demo_specs import generalization_specs
from app.domain.models import SimulationResult
from app.hysys.case_builder import build_base_case
from app.hysys.conversion import configure_conversion_case
from app.main import create_app
from tests.contract.test_case_builder import RecordingSession
from tests.contract.test_conversion_case import RecordingConversionSession
from tests.contract.test_workflow_api import StaticProvider


class GenericRecordingSession(RecordingSession, RecordingConversionSession):
    pass


class GenericWebExecutor:
    def __init__(self, root):
        self.root = root
        self.sessions = []

    async def execute(self, run, event_sink, cancellation_requested):
        session = GenericRecordingSession()
        built = build_base_case(
            session, run.spec, self.root / run.id / "recording-only.hsc", lambda event: None,
        )
        configure_conversion_case(built, run.spec, lambda event: None)
        self.sessions.append(session)
        return SimulationResult(
            run_id=run.id, source="fake", converged=True,
            warnings=["Recording-boundary software test; not a real HYSYS result"],
        )


@pytest.mark.parametrize("scenario", ["shift", "reverse_shift", "methanation"])
def test_new_web_reaction_with_kpa_abs_and_assumption_confirmation(tmp_path, scenario):
    spec = generalization_specs()[scenario]
    payload = spec.model_dump(mode="json", exclude={"reactor_type"})
    payload["feeds"][0]["pressure"]["unit"] = "kPa abs"
    executor = GenericWebExecutor(tmp_path)
    with TestClient(create_app(
        Settings(hysys_artifact_dir=tmp_path, _env_file=None),
        provider=StaticProvider(payload), executor=executor,
    )) as client:
        parsed = client.post("/api/workflows/submit", json={"text": "new reaction"}).json()
        assert parsed["decision"]["reactor_type"] == "conversion"
        assert parsed["run"] is None
        draft = parsed["spec"]
        for assumption in draft["assumptions"]:
            assumption["confirmed"] = True
        prepared = client.post("/api/specs/prepare", json=draft).json()
        assert prepared["executable"]
        response = client.post("/api/runs", json={"spec": prepared["spec"], "auto_start": True})
        assert response.status_code == 201
        run_id = response.json()["id"]
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            run = client.get(f"/api/runs/{run_id}").json()
            if run["state"] in {"succeeded", "failed"}:
                break
            time.sleep(0.01)
        assert run["state"] == "succeeded", run.get("error")
        assert run["result"]["source"] == "fake"
    session = executor.sessions[0]
    assert ("pressure", "Feed", 1000, "kPa") in session.calls
    reaction = next(c for c in session.calls if c[0] == "add_conversion_reaction")
    assert reaction[-2:] == (spec.reactions[0].base_component, spec.known_conversion)
