from app.hysys.case_builder import BuiltCase
from app.hysys.equilibrium import configure_equilibrium_case
from tests.unit.test_steam_reforming_spec import steam_reforming_spec


class RecordingEquilibriumSession:
    def __init__(self):
        self.calls = []

    def create_equilibrium_reaction_set(self, name):
        self.calls.append(("create_reaction_set", name))
        return "reaction-set"

    def add_equilibrium_reaction(self, reaction_set, name, stoichiometry):
        self.calls.append(("add_reaction", reaction_set, name, stoichiometry))

    def create_equilibrium_reactor(self, name):
        self.calls.append(("create_reactor", name))
        return name

    def connect_feed(self, reactor, feed_name):
        self.calls.append(("connect_feed", reactor, feed_name))

    def attach_reaction_set(self, reactor, reaction_set):
        self.calls.append(("attach_reaction_set", reactor, reaction_set))

    def create_energy_stream(self, name):
        self.calls.append(("create_energy_stream", name))
        return name

    def connect_energy_stream(self, reactor, energy_stream):
        self.calls.append(("connect_energy_stream", reactor, energy_stream))

    def set_outlet_temperature(self, reactor, value, unit):
        self.calls.append(("set_outlet_temperature", reactor, value, unit))

    def set_outlet_pressure(self, reactor, value, unit):
        self.calls.append(("set_outlet_pressure", reactor, value, unit))

    def set_pressure_drop(self, reactor, value, unit):
        self.calls.append(("set_pressure_drop", reactor, value, unit))

    def save_case(self, case_path):
        self.calls.append(("save_case", case_path))


def _built(tmp_path, session, name):
    return BuiltCase(
        session=session,
        simulation_case=object(),
        case_path=tmp_path / f"{name}.hsc",
        component_names=[
            "Methane",
            "Water",
            "Carbon Monoxide",
            "Carbon Dioxide",
            "Hydrogen",
        ],
        fluid_package="Peng-Robinson",
        feed_names=["Feed"],
    )


def test_two_equilibrium_cases_share_reactions_feed_and_pressure_but_change_temperature(tmp_path):
    spec = steam_reforming_spec()
    records = []
    for operating_case in spec.operating_cases:
        session = RecordingEquilibriumSession()
        configure_equilibrium_case(
            _built(tmp_path, session, operating_case.name),
            spec,
            operating_case,
            lambda event: None,
        )
        records.append(session.calls)

    for calls in records:
        assert len([call for call in calls if call[0] == "add_reaction"]) == 2
        assert any(call[0] == "connect_feed" and call[-1] == "Feed" for call in calls)
        assert any(call[0] == "create_energy_stream" for call in calls)
        assert ("set_outlet_pressure", "Equilibrium Reactor", 1350, "kPa") in calls
        assert ("set_pressure_drop", "Equilibrium Reactor", 0, "kPa") in calls
    temperatures = [
        next(call[2] for call in calls if call[0] == "set_outlet_temperature")
        for calls in records
    ]
    assert temperatures == [873.15, 983.15]
