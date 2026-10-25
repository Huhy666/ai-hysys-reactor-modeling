import pytest

from app.domain.models import ComponentSpec, ReactionSpec, ReactorType, SimulationSpec
from app.hysys.case_builder import BuiltCase
from app.hysys.conversion import configure_conversion_case
from tests.contract.test_conversion_case import RecordingConversionSession


def test_new_reaction_is_transferred_without_toluene_template(tmp_path):
    session = RecordingConversionSession()
    names = ["Carbon Monoxide", "Water", "Carbon Dioxide", "Hydrogen"]
    spec = SimulationSpec(
        title="新反应：已知转化率的水煤气变换", reactor_type=ReactorType.CONVERSION,
        components=[ComponentSpec(user_name=n) for n in names], known_conversion=0.3,
        reactions=[ReactionSpec(
            id="shift", equation="CO + H2O -> CO2 + H2", base_component="CO",
            stoichiometry={"CO": -1, "H2O": -1, "CO2": 1, "H2": 1},
        )],
    )
    built = BuiltCase(
        session=session, simulation_case=object(), case_path=tmp_path / "new.hsc",
        component_names=names, fluid_package="Peng-Robinson", feed_names=["Feed"],
    )
    configure_conversion_case(built, spec, lambda event: None)
    reaction = next(c for c in session.calls if c[0] == "add_conversion_reaction")
    assert reaction[-2:] == ("Carbon Monoxide", 0.3)
    spec.reactions[0].base_component = None
    with pytest.raises(ValueError, match="base_component"):
        configure_conversion_case(built, spec, lambda event: None)
