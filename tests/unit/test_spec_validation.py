from app.domain.models import (
    Assumption,
    ComponentSpec,
    KineticsSpec,
    Phase,
    Quantity,
    ReactionSpec,
    ReactorType,
    SimulationSpec,
    StreamSpec,
)
from app.domain.validation import validate_spec


def _base_spec(reactor_type: ReactorType) -> SimulationSpec:
    return SimulationSpec(
        title="test reaction",
        components=[
            ComponentSpec(user_name="Methane", formula="CH4", hysys_name="Methane"),
            ComponentSpec(user_name="Hydrogen", formula="H2", hysys_name="Hydrogen"),
        ],
        feeds=[
            StreamSpec(
                name="Feed",
                temperature=Quantity(value=500, unit="K"),
                pressure=Quantity(value=1000, unit="kPa"),
                total_flow=Quantity(value=100, unit="kmol/h"),
                flow_basis="molar",
                composition={"Methane": 1.0},
                phase=Phase.GAS,
            )
        ],
        reactions=[
            ReactionSpec(
                id="R1",
                equation="CH4 -> 2H2 + C",
                stoichiometry={"CH4": -1, "H2": 2, "C": 1},
            )
        ],
        reactor_type=reactor_type,
        fluid_package="Peng-Robinson",
    )


def _codes(spec: SimulationSpec) -> set[str]:
    return {issue.code for issue in validate_spec(spec)}


def test_validate_spec_reports_shared_missing_fields():
    spec = SimulationSpec(title="incomplete", reactor_type=ReactorType.CONVERSION)

    codes = _codes(spec)

    assert {"components_required", "feed_required", "reaction_required"} <= codes


def test_conversion_requires_conversion_and_xylene_selectivity():
    spec = _base_spec(ReactorType.CONVERSION)
    spec.components.extend(
        [
            ComponentSpec(user_name="o-Xylene", formula="C8H10", hysys_name="o-Xylene"),
            ComponentSpec(user_name="m-Xylene", formula="C8H10", hysys_name="m-Xylene"),
            ComponentSpec(user_name="p-Xylene", formula="C8H10", hysys_name="p-Xylene"),
        ]
    )

    codes = _codes(spec)

    assert "conversion_required" in codes
    assert "xylene_selectivity_required" in codes


def test_equilibrium_requires_reversible_reaction_and_equilibrium_capability():
    spec = _base_spec(ReactorType.EQUILIBRIUM)

    codes = _codes(spec)

    assert "reversible_reaction_required" in codes
    assert "equilibrium_data_required" in codes


def test_gibbs_requires_candidate_products_beyond_feed():
    spec = _base_spec(ReactorType.GIBBS)
    spec.candidate_products = ["Methane"]

    assert "candidate_products_required" in _codes(spec)


def test_cstr_requires_complete_kinetics_and_liquid_sizing():
    spec = _base_spec(ReactorType.CSTR)
    spec.feeds[0].phase = Phase.LIQUID
    spec.kinetics = KineticsSpec(rate_expression="r = k*C_A", phase=Phase.LIQUID)

    codes = _codes(spec)

    assert "kinetic_parameters_required" in codes
    assert "cstr_size_required" in codes


def test_pfr_requires_complete_kinetics_and_geometry_or_volume():
    spec = _base_spec(ReactorType.PFR)
    spec.kinetics = KineticsSpec(
        rate_expression="r = k*C_A",
        phase=Phase.GAS,
        parameters={"A": Quantity(value=1000, unit="1/s")},
    )

    codes = _codes(spec)

    assert "pfr_geometry_required" in codes
    assert "kinetic_parameters_required" not in codes


def test_unconfirmed_assumption_blocks_execution():
    spec = _base_spec(ReactorType.CONVERSION)
    spec.known_conversion = 0.5
    spec.assumptions = [Assumption(text="Use equal xylene split", confirmed=False)]

    issues = validate_spec(spec)

    issue = next(issue for issue in issues if issue.code == "assumption_confirmation_required")
    assert issue.severity == "blocking"
    assert issue.field == "assumptions.0.confirmed"


def test_feed_requires_temperature_pressure_flow_basis_and_composition():
    spec = _base_spec(ReactorType.CONVERSION)
    spec.known_conversion = 0.5
    feed = spec.feeds[0]
    feed.temperature = None
    feed.pressure = None
    feed.total_flow = None
    feed.flow_basis = None
    feed.composition = {}

    codes = _codes(spec)

    assert {
        "feed_temperature_required",
        "feed_pressure_required",
        "feed_flow_required",
        "feed_flow_basis_required",
        "feed_composition_required",
    } <= codes
