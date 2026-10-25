import math

import pytest

from app.hysys.case_builder import BuiltCase
from app.hysys.result_reader import read_result
from tests.unit.test_run_repository import _spec


class ResultSession:
    def __init__(self, raw_result):
        self.raw_result = raw_result

    def read_case_result(self, built_case, spec):
        return self.raw_result


def _raw_result():
    return {
        "converged": True,
        "streams": {
            "Product": {
                "temperature_k": 700.0,
                "pressure_kpa": 1200.0,
                "phase": "gas",
                "composition_basis": "mole",
                "mole_fractions": {"Methane": 0.25, "Hydrogen": 0.75},
                "molar_flows_kmol_h": {"Methane": 25.0, "Hydrogen": 75.0},
                "mass_flows_kg_h": {"Methane": 401.0, "Hydrogen": 151.2},
            }
        },
        "reactor_duty_kw": 42.5,
        "warnings": ["engineering check"],
    }


def _built(tmp_path, raw):
    case_path = tmp_path / "result.hsc"
    case_path.write_bytes(b"case")
    return BuiltCase(
        session=ResultSession(raw),
        simulation_case=object(),
        case_path=case_path,
        hysys_version="Aspen HYSYS Version 15 (41.0)",
        component_names=["Methane", "Hydrogen"],
        fluid_package="Peng-Robinson",
        feed_names=["Feed"],
    )


def test_result_reader_returns_normalized_traceable_hysys_result(tmp_path):
    result = read_result(_built(tmp_path, _raw_result()), _spec())

    assert result.source == "hysys"
    assert result.converged is True
    assert result.hysys_version == "Aspen HYSYS Version 15 (41.0)"
    assert result.case_paths == [str((tmp_path / "result.hsc").resolve())]
    assert result.streams["Product"]["temperature_k"] == 700.0
    assert result.streams["Product"]["composition_basis"] == "mole"
    assert result.reactor_duty_kw == 42.5
    assert result.warnings == ["engineering check"]


@pytest.mark.parametrize(
    ("path", "bad_value"),
    [
        (("streams", "Product", "temperature_k"), math.nan),
        (("streams", "Product", "pressure_kpa"), math.inf),
        (("streams", "Product", "molar_flows_kmol_h", "Methane"), -1.0),
        (("streams", "Product", "mass_flows_kg_h", "Methane"), -1.0),
    ],
)
def test_result_reader_rejects_invalid_numbers(tmp_path, path, bad_value):
    raw = _raw_result()
    target = raw
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = bad_value

    with pytest.raises(ValueError, match="invalid HYSYS result"):
        read_result(_built(tmp_path, raw), _spec())


def test_result_reader_requires_boolean_convergence_status(tmp_path):
    raw = _raw_result()
    raw["converged"] = None

    with pytest.raises(ValueError, match="convergence"):
        read_result(_built(tmp_path, raw), _spec())
