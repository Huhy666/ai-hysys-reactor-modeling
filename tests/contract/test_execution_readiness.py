from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.demo_specs import toluene_spec
from app.main import create_app


def test_missing_executor_does_not_leave_an_unconsumed_job(tmp_path):
    with TestClient(create_app(Settings(hysys_artifact_dir=tmp_path, _env_file=None))) as client:
        response = client.post("/api/runs", json={
            "spec": toluene_spec(confirmed=True).model_dump(mode="json"), "auto_start": True,
        })
        assert response.status_code == 503
        assert client.get("/api/runs").json() == []
