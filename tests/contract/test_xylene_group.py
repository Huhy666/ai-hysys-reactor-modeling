import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.demo_specs import toluene_spec
from app.domain.models import ComponentSpec, DraftSimulationSpec, ReactionSpec, SimulationSpec
from app.domain.spec_normalization import expand_confirmed_xylene_group
from app.domain.stoichiometry import check_reaction_balance
from app.hysys.case_builder import BuiltCase
from app.hysys.conversion import configure_conversion_case
from app.main import create_app
from tests.contract.test_conversion_case import RecordingConversionSession


def reported_draft(*, confirmed=False):
    spec = toluene_spec(confirmed=confirmed)
    for item, chinese in zip(spec.components, (
        "甲苯", "苯", "邻二甲苯", "间二甲苯", "对二甲苯",
    ), strict=True):
        item.user_name = chinese
    spec.components.append(ComponentSpec(
        user_name="二甲苯", formula="C8H10", hysys_name=None, matched=False,
    ))
    spec.reactions = [ReactionSpec(
        id="R1", equation="2 甲苯 → 苯 + 二甲苯（邻/间/对）",
        stoichiometry={"Toluene": -2, "Benzene": 1, "二甲苯": 1},
        conversion=0.5, base_component="Toluene",
    )]
    spec.feeds[0].name = "纯甲苯进料"
    spec.feeds[0].temperature.unit = "°C"
    spec.feeds[0].pressure.unit = "kPa(a)"
    return DraftSimulationSpec.model_validate(spec.model_dump() | {"reactor_type": None})


def test_confirmed_reported_draft_expands_group_without_changing_source():
    draft = reported_draft(confirmed=True)
    normalized = expand_confirmed_xylene_group(draft)
    assert len(draft.components) == 6
    assert len(draft.reactions) == 1
    assert len(normalized.components) == 5
    assert len(normalized.reactions) == 3
    assert sum(r.conversion for r in normalized.reactions) == pytest.approx(0.5)
    assert all(check_reaction_balance(r).balanced for r in normalized.reactions)
    assert normalized.feeds == draft.feeds
    assert normalized.assumptions == draft.assumptions


def test_prepared_group_transfers_three_conversion_reactions_to_builder(tmp_path):
    with TestClient(create_app(Settings(hysys_artifact_dir=tmp_path, _env_file=None))) as client:
        prepared = client.post("/api/specs/prepare", json=reported_draft(
            confirmed=True,
        ).model_dump(mode="json")).json()
    spec = SimulationSpec.model_validate(prepared["spec"])
    session = RecordingConversionSession()
    built = BuiltCase(
        session=session, simulation_case=object(), case_path=tmp_path / "conversion.hsc",
        component_names=[c.hysys_name for c in spec.components],
        fluid_package="Peng-Robinson", feed_names=[spec.feeds[0].name],
    )
    configure_conversion_case(built, spec, lambda event: None)
    reactions = [call for call in session.calls if call[0] == "add_conversion_reaction"]
    assert len(reactions) == 3
    assert [call[-1] for call in reactions] == pytest.approx([1 / 6] * 3)
    assert all(call[-2] == "Toluene" for call in reactions)


@pytest.mark.parametrize("confirmed", [False, True])
def test_prepare_api_blocks_before_confirmation_then_returns_executable_spec(tmp_path, confirmed):
    with TestClient(create_app(Settings(hysys_artifact_dir=tmp_path, _env_file=None))) as client:
        body = client.post("/api/specs/prepare", json=reported_draft(
            confirmed=confirmed,
        ).model_dump(mode="json")).json()
    assert body["executable"] is confirmed
    if confirmed:
        assert len(body["spec"]["components"]) == 5
        assert len(body["spec"]["reactions"]) == 3
    else:
        assert "ambiguous_component" in {issue["code"] for issue in body["issues"]}
        assert "xylene_selectivity_required" in {issue["code"] for issue in body["issues"]}


@pytest.mark.parametrize("change", ["missing_isomer", "wrong_stoich", "conflicting_conversion"])
def test_unsupported_group_is_not_silently_rewritten(change):
    draft = reported_draft(confirmed=True)
    if change == "missing_isomer":
        draft.components.pop(4)
    elif change == "wrong_stoich":
        draft.reactions[0].stoichiometry["Toluene"] = -1
    else:
        draft.reactions[0].conversion = 0.6
    normalized = expand_confirmed_xylene_group(draft)
    assert "二甲苯" in normalized.reactions[0].stoichiometry


def test_ambiguous_feed_is_still_blocked(tmp_path):
    draft = reported_draft(confirmed=True)
    draft.feeds[0].composition = {"Toluene": 0.5, "二甲苯": 0.5}
    with TestClient(create_app(Settings(hysys_artifact_dir=tmp_path, _env_file=None))) as client:
        body = client.post("/api/specs/prepare", json=draft.model_dump(mode="json")).json()
    assert body["executable"] is False
    assert any(issue["field"] == "feeds.0.composition" for issue in body["issues"])


@pytest.mark.parametrize("unit", ["kPa(abs)", "kPa (a)", "kPa（绝压）"])
def test_confirmed_ai_draft_accepts_explicit_absolute_unit_variants(tmp_path, unit):
    draft = reported_draft(confirmed=True)
    draft.feeds[0].pressure.unit = unit
    with TestClient(create_app(Settings(hysys_artifact_dir=tmp_path, _env_file=None))) as client:
        body = client.post("/api/specs/prepare", json=draft.model_dump(mode="json")).json()
    assert body["executable"] is True


def test_unknown_unit_is_blocked_before_hysys_queue(tmp_path):
    draft = reported_draft(confirmed=True)
    draft.feeds[0].pressure.unit = "kPa(mystery)"
    with TestClient(create_app(Settings(hysys_artifact_dir=tmp_path, _env_file=None))) as client:
        body = client.post("/api/specs/prepare", json=draft.model_dump(mode="json")).json()
    assert body["executable"] is False
    assert any(issue["code"] == "unsupported_unit" for issue in body["issues"])
