import pytest

from app.domain.models import (
    Assumption,
    ComponentSpec,
    Quantity,
    ReactionSpec,
    ReactorType,
    SimulationSpec,
    StreamSpec,
)
from app.hysys.conversion import (
    build_toluene_parallel_reactions,
    calculate_toluene_reference,
)


def _spec(*, assumptions=None, reactions=None):
    return SimulationSpec(
        title="甲苯歧化",
        reactor_type=ReactorType.CONVERSION,
        components=[
            ComponentSpec(user_name=name, hysys_name=name)
            for name in ("Toluene", "Benzene", "o-Xylene", "m-Xylene", "p-Xylene")
        ],
        feeds=[
            StreamSpec(
                name="Feed",
                temperature=Quantity(value=653.15, unit="K"),
                pressure=Quantity(value=2500, unit="kPa"),
                total_flow=Quantity(value=10000, unit="kg/h"),
                flow_basis="mass",
                composition={"Toluene": 1.0},
            )
        ],
        reactions=reactions or [],
        known_conversion=0.5,
        fluid_package="Peng-Robinson",
        assumptions=assumptions or [],
    )


def test_reference_mass_balance_for_10000_kg_h_and_50_percent_conversion():
    values = calculate_toluene_reference(10000.0, 0.5)

    assert values.feed_toluene_kmol_h == pytest.approx(108.53, rel=2e-4)
    assert values.reacted_toluene_kmol_h == pytest.approx(54.26, rel=2e-4)
    assert values.unreacted_toluene_kmol_h == pytest.approx(54.26, rel=2e-4)
    assert values.benzene_kmol_h == pytest.approx(27.13, rel=2e-4)
    assert values.total_xylene_kmol_h == pytest.approx(27.13, rel=2e-4)


def test_missing_selectivities_block_parallel_reaction_creation():
    with pytest.raises(ValueError, match="selectivit"):
        build_toluene_parallel_reactions(_spec())


def test_confirmed_equal_split_creates_three_parallel_reactions():
    spec = _spec(
        assumptions=[Assumption(text="邻、间、对二甲苯按等选择性分配", confirmed=True)]
    )

    reactions = build_toluene_parallel_reactions(spec)

    assert [reaction.stoichiometry for reaction in reactions] == [
        {"Toluene": -2.0, "Benzene": 1.0, "o-Xylene": 1.0},
        {"Toluene": -2.0, "Benzene": 1.0, "m-Xylene": 1.0},
        {"Toluene": -2.0, "Benzene": 1.0, "p-Xylene": 1.0},
    ]
    assert [reaction.selectivity for reaction in reactions] == pytest.approx([1 / 3] * 3)
    assert [reaction.conversion for reaction in reactions] == pytest.approx([1 / 6] * 3)


def test_explicit_selectivities_are_preserved_and_must_sum_to_one():
    reactions = [
        ReactionSpec(
            id=f"R-{name}",
            equation="2 Toluene -> Benzene + Xylene",
            stoichiometry={"Toluene": -2, "Benzene": 1, name: 1},
            selectivity=selectivity,
        )
        for name, selectivity in zip(
            ("o-Xylene", "m-Xylene", "p-Xylene"),
            (0.2, 0.3, 0.5),
            strict=True,
        )
    ]

    prepared = build_toluene_parallel_reactions(_spec(reactions=reactions))

    assert [reaction.selectivity for reaction in prepared] == [0.2, 0.3, 0.5]
    assert [reaction.conversion for reaction in prepared] == [0.1, 0.15, 0.25]

    reactions[-1].selectivity = 0.4
    with pytest.raises(ValueError, match="sum to 1"):
        build_toluene_parallel_reactions(_spec(reactions=reactions))
