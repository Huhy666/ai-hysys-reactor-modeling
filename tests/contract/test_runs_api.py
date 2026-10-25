import time

from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.models import ReactionSpec, SimulationResult
from app.main import create_app
from tests.unit.test_run_repository import _spec


def _ready_spec():
    spec = _spec()
    spec.reactions = [
        ReactionSpec(
            id="R1",
            equation="CH4 -> products",
            stoichiometry={"Methane": -1, "Hydrogen": 1},
            conversion=0.5,
        )
    ]
    return spec


def test_create_list_get_and_cancel_ready_run(tmp_path):
    client = TestClient(
        create_app(Settings(hysys_artifact_dir=tmp_path, _env_file=None))
    )
    payload = {
        "spec": _ready_spec().model_dump(mode="json"),
        "original_text": "simulate",
    }

    created = client.post("/api/runs", json=payload)
    run_id = created.json()["id"]
    listed = client.get("/api/runs")
    fetched = client.get(f"/api/runs/{run_id}")
    cancelled = client.post(f"/api/runs/{run_id}/cancel")

    assert created.status_code == 201
    assert created.json()["state"] == "ready"
    assert [item["id"] for item in listed.json()] == [run_id]
    assert fetched.json()["id"] == run_id
    assert cancelled.json()["state"] == "cancelled"


def test_unknown_run_returns_404(tmp_path):
    client = TestClient(
        create_app(Settings(hysys_artifact_dir=tmp_path, _env_file=None))
    )

    assert client.get("/api/runs/missing").status_code == 404


def test_artifact_download_rejects_path_traversal(tmp_path):
    client = TestClient(
        create_app(Settings(hysys_artifact_dir=tmp_path, _env_file=None))
    )
    created = client.post(
        "/api/runs",
        json={
            "spec": _ready_spec().model_dump(mode="json"),
            "original_text": "simulate",
        },
    )
    run_id = created.json()["id"]

    response = client.get(f"/api/runs/{run_id}/artifacts/%2E%2E%2Frun.json")

    assert response.status_code in {400, 404}


class CompletingExecutor:
    async def execute(self, run, event_sink, cancellation_requested):
        return SimulationResult(run_id=run.id, source="fake", converged=True)


def test_auto_start_queues_and_executes_ready_run(tmp_path):
    with TestClient(
        create_app(
            Settings(hysys_artifact_dir=tmp_path, _env_file=None),
            executor=CompletingExecutor(),
        )
    ) as client:
        created = client.post(
            "/api/runs",
            json={
                "spec": _ready_spec().model_dump(mode="json"),
                "original_text": "simulate",
                "auto_start": True,
            },
        )
        run_id = created.json()["id"]
        deadline = time.monotonic() + 2
        current = client.get(f"/api/runs/{run_id}").json()
        while current["state"] not in {"succeeded", "failed"} and time.monotonic() < deadline:
            time.sleep(0.01)
            current = client.get(f"/api/runs/{run_id}").json()

    assert created.status_code == 201
    assert current["state"] == "succeeded"
    assert current["result"]["source"] == "fake"
