import pytest

from app.domain.models import (
    ComponentSpec,
    OperatingCaseSpec,
    Quantity,
    ReactionSpec,
    ReactorType,
    SimulationSpec,
    StreamSpec,
)
from app.domain.stoichiometry import check_reaction_balance
from app.hysys.equilibrium import validate_steam_reforming_spec


def steam_reforming_spec():
    return SimulationSpec(
        title="甲烷蒸汽重整",
        reactor_type=ReactorType.EQUILIBRIUM,
        components=[
            ComponentSpec(user_name=name, hysys_name=name)
            for name in (
                "Methane",
                "Water",
                "Carbon Monoxide",
                "Carbon Dioxide",
                "Hydrogen",
            )
        ],
        feeds=[
            StreamSpec(
                name="Feed",
                temperature=Quantity(value=520, unit="degC"),
                pressure=Quantity(value=1350, unit="kPa"),
                total_flow=Quantity(value=3700, unit="kmol/h"),
                flow_basis="molar",
                composition={"Methane": 1000 / 3700, "Water": 2700 / 3700},
            )
        ],
        reactions=[
            ReactionSpec(
                id="Steam Reforming",
                equation="CH4 + H2O <-> CO + 3H2",
                stoichiometry={"CH4": -1, "H2O": -1, "CO": 1, "H2": 3},
                reversible=True,
            ),
            ReactionSpec(
                id="Water Gas Shift",
                equation="CO + H2O <-> CO2 + H2",
                stoichiometry={"CO": -1, "H2O": -1, "CO2": 1, "H2": 1},
                reversible=True,
            ),
        ],
        operating_cases=[
            OperatingCaseSpec(
                name="600C",
                outlet_temperature=Quantity(value=600, unit="degC"),
                outlet_pressure=Quantity(value=1350, unit="kPa"),
                pressure_drop=Quantity(value=0, unit="kPa"),
            ),
            OperatingCaseSpec(
                name="710C",
                outlet_temperature=Quantity(value=710, unit="degC"),
                outlet_pressure=Quantity(value=1350, unit="kPa"),
                pressure_drop=Quantity(value=0, unit="kPa"),
            ),
        ],
        fluid_package="Peng-Robinson",
        equilibrium_data_available=True,
    )


def test_steam_reforming_spec_has_exact_feed_and_two_temperature_cases():
    spec = steam_reforming_spec()

    normalized = validate_steam_reforming_spec(spec)

    assert normalized.feed_temperature_k == pytest.approx(793.15)
    assert normalized.feed_pressure_kpa == 1350
    assert normalized.methane_flow_kmol_h == pytest.approx(1000)
    assert normalized.water_flow_kmol_h == pytest.approx(2700)
    assert normalized.case_temperatures_k == pytest.approx([873.15, 983.15])
    assert normalized.case_pressures_kpa == [1350, 1350]
    assert normalized.pressure_drops_kpa == [0, 0]


def test_both_reforming_reactions_are_element_balanced():
    spec = steam_reforming_spec()
    reports = [check_reaction_balance(reaction) for reaction in spec.reactions]

    assert all(report.balanced for report in reports)
