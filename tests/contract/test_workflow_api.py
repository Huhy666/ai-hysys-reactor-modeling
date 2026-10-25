import time

from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.models import SimulationResult
from app.main import create_app
from tests.contract.test_runs_api import _ready_spec


class StaticProvider:
    last_response_id = "provider-1"

    def __init__(self, payload):
        self.payload = payload

    async def parse_modeling_request(self, text):
        return self.payload


class CompletingExecutor:
    async def execute(self, run, event_sink, cancellation_requested):
        return SimulationResult(run_id=run.id, source="fake", converged=True)


def test_submit_auto_queues_complete_ai_spec(tmp_path):
    payload = _ready_spec().model_dump(mode="json", exclude={"reactor_type"})
    with TestClient(
        create_app(
            Settings(hysys_artifact_dir=tmp_path, _env_file=None),
            provider=StaticProvider(payload),
            executor=CompletingExecutor(),
        )
    ) as client:
        response = client.post("/api/workflows/submit", json={"text": "simulate"})
        body = response.json()
        run_id = body["run"]["id"]
        deadline = time.monotonic() + 2
        current = client.get(f"/api/runs/{run_id}").json()
        while current["state"] not in {"succeeded", "failed"} and time.monotonic() < deadline:
            time.sleep(0.01)
            current = client.get(f"/api/runs/{run_id}").json()

    assert response.status_code == 200
    assert body["executable"] is True
    assert body["decision"]["reactor_type"] == "conversion"
    assert current["state"] == "succeeded"


def test_submit_returns_blockers_without_creating_run(tmp_path):
    payload = _ready_spec().model_dump(mode="json", exclude={"reactor_type"})
    payload["feeds"][0]["pressure"] = None
    with TestClient(
        create_app(
            Settings(hysys_artifact_dir=tmp_path, _env_file=None),
            provider=StaticProvider(payload),
            executor=CompletingExecutor(),
        )
    ) as client:
        response = client.post("/api/workflows/submit", json={"text": "simulate"})
        history = client.get("/api/runs").json()

    body = response.json()
    assert body["executable"] is False
    assert body["run"] is None
    assert "feed_pressure_required" in {issue["code"] for issue in body["issues"]}
    assert history == []
