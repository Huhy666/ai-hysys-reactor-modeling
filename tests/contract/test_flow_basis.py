import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.demo_specs import toluene_spec
from app.domain.models import StreamSpec
from app.hysys.case_builder import build_base_case
from app.main import create_app
from tests.contract.test_case_builder import RecordingSession


@pytest.mark.parametrize(("raw", "expected"), [
    ("Mass", "mass"), (" MASS ", "mass"), ("mass_flow", "mass"),
    ("mass flow rate", "mass"), ("质量流量", "mass"), ("kg/h", "mass"),
    ("Molar", "molar"), ("mole", "molar"), ("摩尔流量", "molar"),
    ("molar_flow", "molar"), ("kmol/hr", "molar"),
])
def test_explicit_flow_basis_variants(raw, expected):
    assert StreamSpec(name="Feed", flow_basis=raw).flow_basis == expected


@pytest.mark.parametrize("basis", ["Mass", "mass_flow", "质量流量"])
def test_ai_mass_basis_is_transferred_to_case_builder(tmp_path, basis):
    payload = toluene_spec(confirmed=True).model_dump(mode="json")
    payload["feeds"][0]["flow_basis"] = basis
    with TestClient(create_app(Settings(hysys_artifact_dir=tmp_path, _env_file=None))) as client:
        response = client.post("/api/specs/prepare", json=payload).json()
    assert response["executable"]
    spec = type(toluene_spec()).model_validate(response["spec"])
    session = RecordingSession()
    build_base_case(session, spec, tmp_path / "conversion.hsc", lambda event: None)
    assert ("flow", "Feed", 10000, "kg/h") in session.calls


@pytest.mark.parametrize(("basis", "code"), [
    ("volumetric", "invalid_flow_basis"),
    ("molar", "unsupported_unit"),
])
def test_unknown_or_conflicting_basis_is_blocked_before_execution(tmp_path, basis, code):
    payload = toluene_spec(confirmed=True).model_dump(mode="json")
    payload["feeds"][0]["flow_basis"] = basis
    with TestClient(create_app(Settings(hysys_artifact_dir=tmp_path, _env_file=None))) as client:
        response = client.post("/api/specs/prepare", json=payload).json()
    assert not response["executable"]
    assert code in {issue["code"] for issue in response["issues"]}
