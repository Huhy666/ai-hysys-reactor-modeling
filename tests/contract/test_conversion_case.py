from app.domain.models import Assumption
from app.hysys.case_builder import BuiltCase
from app.hysys.conversion import configure_conversion_case
from tests.unit.test_toluene_mass_balance import _spec


class RecordingConversionSession:
    version = "V15"

    def __init__(self):
        self.calls = []

    def create_reaction_set(self, name):
        self.calls.append(("create_reaction_set", name))
        return name

    def add_conversion_reaction(
        self, reaction_set, name, stoichiometry, base_component, conversion
    ):
        self.calls.append(
            (
                "add_conversion_reaction",
                reaction_set,
                name,
                stoichiometry,
                base_component,
                conversion,
            )
        )

    def create_conversion_reactor(self, name):
        self.calls.append(("create_conversion_reactor", name))
        return "reactor-object"

    def connect_feed(self, reactor, feed_name):
        self.calls.append(("connect_feed", reactor, feed_name))

    def attach_reaction_set(self, reactor, reaction_set):
        self.calls.append(("attach_reaction_set", reactor, reaction_set))

    def set_adiabatic(self, reactor, enabled):
        self.calls.append(("set_adiabatic", reactor, enabled))

    def save_case(self, case_path):
        self.calls.append(("save_case", case_path))


def test_conversion_builder_transfers_three_reactions_and_adiabatic_assumption(tmp_path):
    session = RecordingConversionSession()
    case_path = tmp_path / "toluene.hsc"
    built_case = BuiltCase(
        session=session,
        simulation_case=object(),
        case_path=case_path,
        component_names=["Toluene", "Benzene", "o-Xylene", "m-Xylene", "p-Xylene"],
        fluid_package="Peng-Robinson",
        feed_names=["Feed"],
    )
    spec = _spec(
        assumptions=[Assumption(text="邻、间、对二甲苯按等选择性分配", confirmed=True)]
    )

    configured = configure_conversion_case(built_case, spec, lambda event: None)

    assert configured.name == "Conversion Reactor"
    reaction_calls = [call for call in session.calls if call[0] == "add_conversion_reaction"]
    assert len(reaction_calls) == 3
    assert [call[-1] for call in reaction_calls] == [1 / 6, 1 / 6, 1 / 6]
    assert ("connect_feed", "reactor-object", "Feed") in session.calls
    assert ("set_adiabatic", "reactor-object", True) in session.calls
    assert session.calls[-1] == ("save_case", case_path)
