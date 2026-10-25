from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.runtime import source_build_id


def test_source_identity_is_sensitive_to_unit_and_builder_changes(tmp_path):
    unit = tmp_path / "domain" / "units.py"
    unit.parent.mkdir()
    unit.write_text("old units\n", encoding="utf-8")
    first = source_build_id(tmp_path)
    unit.write_text("new units\n", encoding="utf-8")
    assert source_build_id(tmp_path) != first


def test_source_identity_is_independent_of_windows_line_endings(tmp_path):
    unit = tmp_path / "domain" / "units.py"
    unit.parent.mkdir()
    unit.write_bytes(b"line one\r\nline two\r\n")
    first = source_build_id(tmp_path)
    unit.write_bytes(b"line one\nline two\n")
    assert source_build_id(tmp_path) == first


def test_runtime_snapshot_does_not_change_without_restart(tmp_path, monkeypatch):
    monkeypatch.setattr("app.runtime.source_build_id", lambda: "old-startup")
    client = TestClient(create_app(Settings(hysys_artifact_dir=tmp_path, _env_file=None)))
    monkeypatch.setattr("app.runtime.source_build_id", lambda: "new-on-disk")
    body = client.get("/api/runtime").json()
    assert body["build_id"] == "old-startup"
    assert set(body) == {"build_id", "started_at", "identity_kind"}
