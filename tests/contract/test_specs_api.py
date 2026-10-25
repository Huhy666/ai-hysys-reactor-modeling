from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.contract.test_runs_api import _ready_spec
from tests.unit.test_run_repository import _spec


def test_validate_spec_returns_deterministic_decision(tmp_path):
    client = TestClient(
        create_app(Settings(hysys_artifact_dir=tmp_path, _env_file=None))
    )

    response = client.post("/api/specs/validate", json=_spec().model_dump(mode="json"))

    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["reactor_type"] == "conversion"
    assert body["decision"]["reason_codes"] == ["USER_EXPLICIT"]
    assert any(issue["code"] == "reaction_required" for issue in body["issues"])


def test_parse_endpoint_reports_unconfigured_provider_without_secret(tmp_path):
    client = TestClient(
        create_app(Settings(hysys_artifact_dir=tmp_path, _env_file=None))
    )

    response = client.post("/api/specs/parse", json={"text": "模拟甲烷重整"})

    assert response.status_code == 503
    assert response.json()["detail"] == "language-model provider is not configured"


def test_prepare_promotes_complete_draft_to_executable_spec(tmp_path):
    client = TestClient(
        create_app(Settings(hysys_artifact_dir=tmp_path, _env_file=None))
    )

    response = client.post(
        "/api/specs/prepare",
        json=_ready_spec().model_dump(mode="json", exclude={"reactor_type"}),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["executable"] is True
    assert body["spec"]["reactor_type"] == "conversion"
    assert body["decision"]["reason_codes"] == ["KNOWN_CONVERSION"]
    assert body["issues"] == []


def test_prepare_keeps_incomplete_draft_out_of_execution(tmp_path):
    client = TestClient(
        create_app(Settings(hysys_artifact_dir=tmp_path, _env_file=None))
    )
    draft = _ready_spec().model_dump(mode="json", exclude={"reactor_type"})
    draft["feeds"][0]["pressure"] = None

    response = client.post("/api/specs/prepare", json=draft)

    assert response.status_code == 200
    body = response.json()
    assert body["executable"] is False
    assert "feed_pressure_required" in {issue["code"] for issue in body["issues"]}
