import pytest

from app.domain.demo_specs import toluene_spec
from app.domain.result_validation import validate_stream_balance
from app.domain.validation import validate_spec


def stream(molar, mass):
    return {"molar_flows_kmol_h": molar, "mass_flows_kg_h": mass}


def test_balances_real_component_values_and_rejects_missing_carbon():
    inlet = {"Feed": stream({"Toluene": 100}, {"Toluene": 9214})}
    outlet = {"Product": stream(
        {"Toluene": 50, "Benzene": 25, "p-Xylene": 25},
        {"Toluene": 4607, "Benzene": 1952.75, "p-Xylene": 2654.25},
    )}
    assert validate_stream_balance(inlet, outlet)["passed"]
    outlet["Product"]["molar_flows_kmol_h"]["Benzene"] = 20
    with pytest.raises(ValueError, match="balance failed"):
        validate_stream_balance(inlet, outlet)


@pytest.mark.parametrize("mass", [-1, float("nan"), float("inf"), 0])
def test_invalid_inlet_cannot_pass_balance(mass):
    with pytest.raises(ValueError):
        validate_stream_balance(
            {"Feed": stream({"Methane": 1}, {"Methane": mass})},
            {"Out": stream({"Methane": 1}, {"Methane": 16})},
        )


def test_equal_split_confirmation_unblocks_toluene():
    assert validate_spec(toluene_spec())
    assert not validate_spec(toluene_spec(confirmed=True))
