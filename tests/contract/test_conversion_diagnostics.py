import json

import pytest

from scripts.inspect_conversion_case import find_failed_run
from tests.contract.test_v15_session import opened_session as opened_session


def test_diagnostic_reports_measured_conversion_without_changing_target(opened_session, tmp_path):
    session, _, _, _ = opened_session
    session.create_case(tmp_path / "conversion.hsc")
    for name in ("Toluene", "Benzene", "o-Xylene"):
        session.add_component(name)
    session.set_fluid_package("Peng-Robinson")
    feed = session.create_material_stream("Feed")
    feed.ComponentMolarFlow.value = (100, 0, 0)
    feed.ComponentMassFlow.value = (9214, 0, 0)
    reaction_set = session.create_reaction_set("Reactions")
    session.add_conversion_reaction(reaction_set, "R", {
        "Toluene": -2, "Benzene": 1, "o-Xylene": 1,
    }, "Toluene", 0.5)
    reactor = session.create_conversion_reactor("Conversion Reactor")
    session.attach_reaction_set(reactor, reaction_set)
    session.connect_feed(reactor, "Feed")
    for stream, phase in session._output_streams.values():
        stream.Temperature.value = 650
        stream.Pressure.value = 2500
        stream.ComponentMolarFlow.value = (75, 12.5, 12.5) if phase == "gas" else (0, 0, 0)
        stream.ComponentMassFlow.value = (
            (6910.5, 976.375, 1327.125) if phase == "gas" else (0, 0, 0)
        )
    with pytest.raises(ValueError, match="actual_conversion=0.25"):
        session._solution_snapshot()
    output = tmp_path / "solver-diagnostics.json"
    session.write_solver_diagnostics(output)
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["conversion_checks"]["Toluene"] == {
        "inlet_kmol_h": 100, "outlet_kmol_h": 75, "expected_outlet_kmol_h": 50,
        "target_conversion": 0.5, "actual_conversion": 0.25,
    }
    assert report["attached_reactions"][0]["conversion_coefficients"] == [50, 0, 0]
    assert report["database_component_order"] == ["Toluene", "Benzene", "o-Xylene"]
    assert session._conversion_targets == {"Toluene": 0.5}


def test_inspector_selects_latest_failed_conversion_with_saved_case(tmp_path):
    for name, timestamp, saved in (("old", "2026-10-25", True),
                                    ("latest", "2026-10-26", True),
                                    ("missing", "2026-10-27", False)):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "run.json").write_text(json.dumps({
            "state": "failed", "error": "specified conversion not reached: Toluene",
            "updated_at": timestamp,
        }), encoding="utf-8")
        if saved:
            (directory / "conversion.hsc").write_bytes(b"test fixture")
    assert find_failed_run(tmp_path) == tmp_path / "latest"


def test_inspector_does_not_fall_back_to_unrelated_case(tmp_path):
    with pytest.raises(FileNotFoundError):
        find_failed_run(tmp_path)
