import pytest

from app.domain.models import (
    ComponentSpec,
    DraftSimulationSpec,
    KineticsSpec,
    Phase,
    Quantity,
    ReactionSpec,
    ReactorType,
    StreamSpec,
)
from app.domain.reactor_selection import select_reactor


def _draft(**overrides) -> DraftSimulationSpec:
    values = {
        "title": "reaction",
        "components": [
            ComponentSpec(user_name="Methane", formula="CH4", hysys_name="Methane"),
            ComponentSpec(user_name="Hydrogen", formula="H2", hysys_name="Hydrogen"),
        ],
        "feeds": [
            StreamSpec(
                name="Feed",
                temperature=Quantity(value=800, unit="K"),
                pressure=Quantity(value=1000, unit="kPa"),
                total_flow=Quantity(value=100, unit="kmol/h"),
                flow_basis="molar",
                composition={"Methane": 1.0},
                phase=Phase.GAS,
            )
        ],
        "reactions": [
            ReactionSpec(
                id="R1",
                equation="CH4 <=> 2H2 + C",
                stoichiometry={"CH4": -1, "H2": 2, "C": 1},
                reversible=True,
            )
        ],
        "fluid_package": "Peng-Robinson",
    }
    values.update(overrides)
    return DraftSimulationSpec(**values)


@pytest.mark.parametrize(
    ("spec", "expected_type", "reason"),
    [
        (_draft(known_conversion=0.5), ReactorType.CONVERSION, "KNOWN_CONVERSION"),
        (
            _draft(equilibrium_data_available=True),
            ReactorType.EQUILIBRIUM,
            "REVERSIBLE_WITH_EQUILIBRIUM_DATA",
        ),
        (
            _draft(
                reactions=[],
                candidate_products=["Carbon Dioxide", "Water", "Hydrogen"],
                product_distribution_unknown=True,
                high_temperature=True,
            ),
            ReactorType.GIBBS,
            "UNKNOWN_HIGH_TEMPERATURE_PRODUCTS",
        ),
        (
            _draft(
                equipment_kind="tubular",
                kinetics=KineticsSpec(
                    rate_expression="r=k*C_A",
                    phase=Phase.GAS,
                    parameters={"A": Quantity(value=1000, unit="1/s")},
                    length=Quantity(value=10, unit="m"),
                    diameter=Quantity(value=0.1, unit="m"),
                ),
            ),
            ReactorType.PFR,
            "COMPLETE_GAS_KINETICS",
        ),
        (
            _draft(
                equipment_kind="mixed_vessel",
                feeds=[
                    StreamSpec(
                        name="Feed",
                        temperature=Quantity(value=300, unit="K"),
                        pressure=Quantity(value=500, unit="kPa"),
                        total_flow=Quantity(value=1000, unit="kg/h"),
                        flow_basis="mass",
                        composition={"Methane": 1.0},
                        phase=Phase.LIQUID,
                    )
                ],
                kinetics=KineticsSpec(
                    rate_expression="r=k*C_A",
                    phase=Phase.LIQUID,
                    parameters={"A": Quantity(value=1, unit="1/s")},
                    reactor_volume=Quantity(value=1, unit="m3"),
                ),
            ),
            ReactorType.CSTR,
            "COMPLETE_LIQUID_KINETICS",
        ),
    ],
)
def test_select_reactor_uses_deterministic_decision_table(spec, expected_type, reason):
    decision = select_reactor(spec)

    assert decision.reactor_type is expected_type
    assert reason in decision.reason_codes


def test_explicit_compatible_choice_wins():
    decision = select_reactor(_draft(reactor_type=ReactorType.CONVERSION, known_conversion=0.5))

    assert decision.reactor_type is ReactorType.CONVERSION
    assert decision.reason_codes[0] == "USER_EXPLICIT"
    assert decision.blocking_issues == []


def test_explicit_incompatible_choice_returns_blockers():
    decision = select_reactor(_draft(reactor_type=ReactorType.PFR))

    assert decision.reactor_type is ReactorType.PFR
    assert {issue.code for issue in decision.blocking_issues} >= {
        "kinetics_required",
        "pfr_geometry_required",
    }


def test_incomplete_kinetics_does_not_override_known_conversion():
    decision = select_reactor(
        _draft(
            known_conversion=0.5,
            kinetics=KineticsSpec(rate_expression="r=k*C_A", phase=Phase.GAS),
        )
    )

    assert decision.reactor_type is ReactorType.CONVERSION


def test_polymerization_is_explicitly_unsupported():
    decision = select_reactor(_draft(process_kind="polymerization"))

    assert decision.reactor_type is None
    assert {issue.code for issue in decision.blocking_issues} == {"polymerization_unsupported"}


def test_missing_xylene_selectivity_blocks_conversion_execution():
    spec = _draft(reactor_type=ReactorType.CONVERSION, known_conversion=0.5)
    spec.components.extend(
        [
            ComponentSpec(user_name="o-Xylene", formula="C8H10"),
            ComponentSpec(user_name="m-Xylene", formula="C8H10"),
            ComponentSpec(user_name="p-Xylene", formula="C8H10"),
        ]
    )

    decision = select_reactor(spec)

    assert "xylene_selectivity_required" in {
        issue.code for issue in decision.blocking_issues
    }

