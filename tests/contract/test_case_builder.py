from pathlib import Path

import pytest

from app.domain.demo_specs import toluene_spec
from app.domain.models import (
    ComponentSpec,
    Quantity,
    ReactorType,
    SimulationSpec,
    StreamSpec,
)
from app.hysys.case_builder import build_base_case


class RecordingSession:
    def __init__(self):
        self.calls = []

    def create_case(self, case_path):
        self.calls.append(("create_case", Path(case_path)))
        return object()

    def add_component(self, name):
        self.calls.append(("add_component", name))

    def set_fluid_package(self, name):
        self.calls.append(("set_fluid_package", name))

    def create_material_stream(self, name):
        self.calls.append(("create_material_stream", name))
        return name

    def set_stream_temperature(self, stream, value, unit):
        self.calls.append(("temperature", stream, value, unit))

    def set_stream_pressure(self, stream, value, unit):
        self.calls.append(("pressure", stream, value, unit))

    def set_stream_flow(self, stream, value, unit):
        self.calls.append(("flow", stream, value, unit))

    def set_stream_composition(self, stream, composition):
        self.calls.append(("composition", stream, composition))

    def save_case(self, case_path):
        self.calls.append(("save_case", Path(case_path)))


def test_reported_ai_absolute_pressure_reaches_hysys_in_internal_units(tmp_path):
    spec = toluene_spec(confirmed=True)
    spec.feeds[0].name = "甲苯进料"
    spec.feeds[0].pressure.unit = "kPa absolute"
    spec.feeds[0].temperature.unit = "°C"
    session = RecordingSession()
    build_base_case(session, spec, tmp_path / "conversion.hsc", lambda event: None)
    assert ("pressure", "甲苯进料", 2500.0, "kPa") in session.calls
    assert ("temperature", "甲苯进料", 653.15, "K") in session.calls
    assert ("flow", "甲苯进料", 10000.0, "kg/h") in session.calls


def _spec(pressure_unit="MPa"):
    return SimulationSpec(
        title="base case",
        reactor_type=ReactorType.CONVERSION,
        components=[
            ComponentSpec(user_name="甲烷"),
            ComponentSpec(user_name="Water", hysys_name="Water"),
            ComponentSpec(user_name="CH4"),
        ],
        feeds=[
            StreamSpec(
                name="Feed",
                temperature=Quantity(value=380, unit="degC"),
                pressure=Quantity(value=2.5, unit=pressure_unit),
                total_flow=Quantity(value=100, unit="kmol/h"),
                flow_basis="molar",
                composition={"CH4": 2, "Water": 1},
            )
        ],
        fluid_package="Peng-Robinson",
        known_conversion=0.5,
    )


def test_builder_writes_unique_components_and_explicit_internal_units(tmp_path):
    session = RecordingSession()
    case_path = tmp_path / "run-1" / "case.hsc"

    built = build_base_case(session, _spec(), case_path, lambda event: None)

    assert built.case_path == case_path.resolve()
    assert session.calls == [
        ("create_case", case_path.resolve()),
        ("add_component", "Methane"),
        ("add_component", "Water"),
        ("set_fluid_package", "Peng-Robinson"),
        ("create_material_stream", "Feed"),
        ("temperature", "Feed", 653.15, "K"),
        ("pressure", "Feed", 2500.0, "kPa"),
        ("flow", "Feed", 100, "kmol/h"),
        ("composition", "Feed", {"Methane": pytest.approx(2 / 3), "Water": pytest.approx(1 / 3)}),
        ("save_case", case_path.resolve()),
    ]


def test_builder_rejects_gauge_pressure_before_session_call(tmp_path):
    session = RecordingSession()

    with pytest.raises(ValueError, match="gauge pressure"):
        build_base_case(session, _spec("barg"), tmp_path / "case.hsc", lambda event: None)

    assert session.calls == []


def test_builder_requires_explicit_fluid_package(tmp_path):
    session = RecordingSession()
    spec = _spec()
    spec.fluid_package = None

    with pytest.raises(ValueError, match="fluid package"):
        build_base_case(session, spec, tmp_path / "case.hsc", lambda event: None)

    assert session.calls == []
