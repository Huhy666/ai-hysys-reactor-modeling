import json

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_missing_llm_configuration_is_not_configured(tmp_path):
    settings = Settings(hysys_artifact_dir=tmp_path, _env_file=None)
    client = TestClient(create_app(settings))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "app": {"status": "ok", "environment": "development"},
        "ai": {"status": "not_configured", "provider": "openai"},
        "hysys": {"status": "not_probed"},
    }


def test_health_never_returns_secret_values(tmp_path):
    secret = "do-not-leak-this-key"
    settings = Settings(
        llm_base_url="https://example.invalid/v1",
        llm_api_key=secret,
        llm_model="test-model",
        hysys_artifact_dir=tmp_path,
        _env_file=None,
    )
    client = TestClient(create_app(settings))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["ai"] == {"status": "configured", "provider": "openai"}
    assert secret not in response.text


def test_health_reads_verified_hysys_probe_report(tmp_path):
    report_path = tmp_path / "probe-result.json"
    report_path.write_text(
        json.dumps(
            {
                "all_required": True,
                "version": "Aspen HYSYS Version 15 (41.0)",
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(
        hysys_artifact_dir=tmp_path / "runs",
        hysys_probe_result_path=report_path,
        _env_file=None,
    )

    response = TestClient(create_app(settings)).get("/api/health")

    assert response.json()["hysys"] == {
        "status": "ready",
        "version": "Aspen HYSYS Version 15 (41.0)",
    }
