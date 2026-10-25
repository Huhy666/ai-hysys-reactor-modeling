from pathlib import Path

import pytest

from app.config import Settings
from app.hysys.v15_session import V15CaseSession


class Variable:
    def __init__(self, value=None):
        self.value = value
        self.calls = []

    def SetValue(self, value, unit):
        self.value = value
        self.calls.append(("SetValue", value, unit))

    def GetValue(self, unit):
        self.calls.append(("GetValue", unit))
        return self.value

    def SetValues(self, values, unit):
        self.value = tuple(values)
        self.calls.append(("SetValues", tuple(values), unit))

    def GetValues(self, unit):
        self.calls.append(("GetValues", unit))
        return self.value

    @property
    def Values(self):
        return self.value

    @Values.setter
    def Values(self, value):
        self.value = tuple(value)


class Collection:
    def __init__(self, factory=None, initial=None):
        self.factory = factory or (lambda name, *args: NamedObject(name))
        self.items = dict(initial or {})
        self.add_calls = []

    @property
    def Count(self):
        return len(self.items)

    def Add(self, name, *args):
        self.add_calls.append((name, *args))
        item = self.factory(name, *args)
        self.items[name] = item
        return item

    def Item(self, key):
        if isinstance(key, int):
            return list(self.items.values())[key]
        return self.items[key]


class NamedObject:
    def __init__(self, name):
        self.name = name


class PureComponent(NamedObject):
    TypeName = "purecomp"


class ComponentList(NamedObject):
    def __init__(self, name):
        super().__init__(name)
        self.Components = Collection(factory=PureComponent)


class Basis(NamedObject):
    def __init__(self, name):
        super().__init__(name)
        self.IsChangingBasis = False
        self.CanEndBasisChange = True
        self.start_calls = 0
        self.end_calls = 0

    def StartBasisChange(self):
        self.start_calls += 1
        self.IsChangingBasis = True

    def EndBasisChange(self):
        self.end_calls += 1
        self.IsChangingBasis = False


class MaterialStream(NamedObject):
    def __init__(self, name):
        super().__init__(name)
        self.Temperature = Variable()
        self.Pressure = Variable()
        self.MolarFlow = Variable()
        self.MassFlow = Variable()
        self.ComponentMolarFraction = Variable()
        self.ComponentMolarFlow = Variable()
        self.ComponentMassFlow = Variable()


class ReactionNames:
    def __init__(self, reactants):
        self.reactants = reactants

    @property
    def value(self):
        return (*self.reactants.items, "")

    @property
    def Values(self):
        return self.value


class Reaction(NamedObject):
    def __init__(self, name, type_name):
        super().__init__(name)
        self.TypeName = type_name
        self.Reactants = Collection()
        self.ReactantName = ReactionNames(self.Reactants)
        self.ReactantStoichCoef = Variable()
        self.ConversionCoefficients = Variable()
        self._base_component = None

    @property
    def BaseComponent(self):
        return self._base_component

    @BaseComponent.setter
    def BaseComponent(self, value):
        if not isinstance(value, PureComponent):
            raise TypeError("BaseComponent requires a pure component object")
        self._base_component = value


class ReactionSet(NamedObject):
    def __init__(self, name, _type_name):
        super().__init__(name)
        self.ActiveReactions = Collection(factory=lambda item, *args: item)
        self.associated_package = None

    def AssociateFluidPackage(self, package):
        self.associated_package = package


class Reactor(NamedObject):
    def __init__(self, name, type_name):
        super().__init__(name)
        self.TypeName = type_name
        self.Feeds = Collection(factory=lambda item, *args: item)
        self.ReactionSet = None
        self.ActAsSeparatorWhenCannotSolve = True
        self.IsIgnored = False
        self.VapourProduct = None
        self.LiquidProduct = None
        self.EnergyStream = None
        self.PressureDrop = Variable()
        self._heat_flow = Variable()

    @property
    def HeatFlow(self):
        if self.EnergyStream is None:
            raise PermissionError("Heat flow requires a connected energy stream")
        return self._heat_flow


class FakeCase:
    def __init__(self):
        self.component_list = ComponentList("Components")
        self.fluid_package = NamedObject("Peng-Robinson")
        self.fluid_package.PropertyPackageName = "Peng-Robinson"
        self.fluid_package.ComponentList = self.component_list
        manager = NamedObject("ReactionPackageManager")
        manager.ReactionSets = Collection(factory=ReactionSet)
        manager.Reactions = Collection(factory=Reaction)
        basis = Basis("Basis")
        basis.ComponentLists = Collection(
            factory=ComponentList,
            initial={"default": self.component_list},
        )
        basis.FluidPackages = Collection(initial={"default": self.fluid_package})
        basis.ReactionPackageManager = manager
        self.BasisManager = basis

        flowsheet = NamedObject("Flowsheet")
        flowsheet.MaterialStreams = Collection(factory=MaterialStream)
        flowsheet.EnergyStreams = Collection()
        flowsheet.Operations = Collection(factory=Reactor)
        self.Flowsheet = flowsheet
        self.Solver = NamedObject("Solver")
        self.Solver.CanSolve = True
        self.Visible = False
        self.save_calls = 0
        self.close_calls = []

    def Save(self):
        self.save_calls += 1

    def Close(self, save):
        self.close_calls.append(save)


@pytest.fixture
def opened_session(tmp_path):
    seed = tmp_path / "seed.hsc"
    seed.write_bytes(b"verified seed")
    case = FakeCase()
    application = NamedObject("HYSYS")
    application.Version = "Aspen HYSYS Version 15 (41.0)"
    settings = Settings(hysys_base_case_path=seed, hysys_visible=False)
    opened = []

    def opener(path, progid):
        opened.append((Path(path), progid))
        return case, application, False

    session = V15CaseSession(settings, application=application, opener=opener)
    return session, case, seed, opened


def test_session_copies_seed_and_writes_explicit_stream_units(opened_session, tmp_path):
    session, case, seed, opened = opened_session
    target = tmp_path / "run" / "case.hsc"

    assert session.create_case(target) is case
    session.add_component("Methane")
    session.add_component("Water")
    session.set_fluid_package("Peng-Robinson")
    feed = session.create_material_stream("Feed")
    session.set_stream_temperature(feed, 793.15, "K")
    session.set_stream_pressure(feed, 1350.0, "kPa")
    session.set_stream_flow(feed, 3700.0, "kmol/h")
    session.set_stream_composition(feed, {"Methane": 10 / 37, "Water": 27 / 37})
    session.save_case(target)

    assert target.read_bytes() == seed.read_bytes()
    assert opened == [(target.resolve(), "HYSYS.Application")]
    assert case.Solver.CanSolve is False
    dedicated = case.BasisManager.ComponentLists.Item("AI HYSYS Components")
    assert dedicated.Components.add_calls == [("Methane",), ("H2O",)]
    assert feed.Temperature.calls == [("SetValue", 793.15, "K")]
    assert feed.Pressure.calls == [("SetValue", 1350.0, "kPa")]
    assert feed.MolarFlow.calls == [("SetValue", 3700.0, "kgmole/h")]
    assert feed.ComponentMolarFraction.calls == [
        ("SetValues", pytest.approx((10 / 37, 27 / 37)), "")
    ]
    assert case.save_calls == 1


def test_session_reads_molar_flow_in_hysys_units(opened_session, tmp_path):
    session, _, _, _ = opened_session
    session.create_case(tmp_path / "readback.hsc")
    session.add_component("Methane")
    stream = session.create_material_stream("Product")
    stream.ComponentMolarFraction.value = (1.0,)
    stream.ComponentMolarFlow.value = (3700.0,)
    stream.ComponentMassFlow.value = (59356.0,)
    stream.Temperature.value = 793.15
    stream.Pressure.value = 1350.0
    session._output_streams["Product"] = (stream, "vapour")
    feed = session.create_material_stream("Feed")
    feed.ComponentMolarFlow.value = (3700.0,)
    feed.ComponentMassFlow.value = (59356.0,)
    session._connected_feeds.append(feed)

    result = session.read_case_result(None, None)

    assert stream.ComponentMolarFlow.calls == [("GetValues", "kgmole/h")]
    assert result["streams"]["Product"]["molar_flows_kmol_h"] == {"Methane": 3700.0}


def test_session_identifies_solver_pause_failure(tmp_path):
    seed = tmp_path / "seed.hsc"
    seed.write_bytes(b"verified seed")
    case = FakeCase()

    class AccessDeniedSolver:
        @property
        def CanSolve(self):
            return True

        @CanSolve.setter
        def CanSolve(self, value):
            raise PermissionError("access denied")

    case.Solver = AccessDeniedSolver()
    application = NamedObject("HYSYS")
    application.Version = "Aspen HYSYS Version 15 (41.0)"
    settings = Settings(hysys_base_case_path=seed, hysys_visible=True)
    session = V15CaseSession(
        settings,
        opener=lambda path, progid: (case, application, False),
    )

    with pytest.raises(
        RuntimeError,
        match="initializing copied HYSYS case failed at pause_solver",
    ):
        session.create_case(tmp_path / "run.hsc")


def test_session_identifies_component_add_failure(opened_session, tmp_path):
    session, case, _, _ = opened_session
    session.create_case(tmp_path / "run.hsc")

    class AccessDeniedComponents:
        def Add(self, name):
            raise PermissionError("access denied")

    dedicated = case.BasisManager.ComponentLists.Item("AI HYSYS Components")
    dedicated.Components = AccessDeniedComponents()

    with pytest.raises(
        RuntimeError,
        match="HYSYS COM operation failed at add_component:Methane",
    ):
        session.add_component("Methane")


def test_session_reuses_component_already_present_in_seed(opened_session, tmp_path):
    session, case, _, _ = opened_session
    session.create_case(tmp_path / "run.hsc")
    existing = NamedObject("Methane")

    class ExistingComponents:
        def Item(self, name):
            assert name == "Methane"
            return existing

        def Add(self, name):
            raise AssertionError(f"duplicate component added: {name}")

    dedicated = case.BasisManager.ComponentLists.Item("AI HYSYS Components")
    dedicated.Components = ExistingComponents()

    session.add_component("Methane")
    stream = session.create_material_stream("Feed")
    session.set_stream_composition(stream, {"Methane": 1.0})

    assert stream.ComponentMolarFraction.value == (1.0,)


def test_session_builds_dedicated_component_list_inside_basis_change(
    opened_session, tmp_path
):
    session, case, _, _ = opened_session

    session.create_case(tmp_path / "run.hsc")
    session.add_component("Methane")
    session.add_component("Water")
    session.set_fluid_package("Peng-Robinson")

    component_lists = case.BasisManager.ComponentLists
    dedicated = component_lists.Item("AI HYSYS Components")
    assert case.BasisManager.start_calls == 1
    assert component_lists.add_calls == [("AI HYSYS Components",)]
    assert dedicated.Components.add_calls == [("Methane",), ("H2O",)]
    assert case.fluid_package.ComponentList is dedicated
    assert case.BasisManager.end_calls == 1


def test_session_uses_h2o_database_identifier_for_water(opened_session, tmp_path):
    session, case, _, _ = opened_session
    session.create_case(tmp_path / "run.hsc")

    session.add_component("Water")
    session.set_fluid_package("Peng-Robinson")
    feed = session.create_material_stream("Feed")
    session.set_stream_composition(feed, {"Water": 1.0})

    dedicated = case.BasisManager.ComponentLists.Item("AI HYSYS Components")
    assert dedicated.Components.add_calls == [("H2O",)]
    assert feed.ComponentMolarFraction.value == (1.0,)


def test_session_uses_formula_database_identifiers_for_carbon_oxides(
    opened_session, tmp_path
):
    session, case, _, _ = opened_session
    session.create_case(tmp_path / "run.hsc")

    session.add_component("Carbon Monoxide")
    session.add_component("Carbon Dioxide")

    dedicated = case.BasisManager.ComponentLists.Item("AI HYSYS Components")
    assert dedicated.Components.add_calls == [("CO",), ("CO2",)]


def test_session_identifies_case_close_failure(opened_session, tmp_path):
    session, case, _, _ = opened_session
    session.create_case(tmp_path / "run.hsc")

    def deny_close(save):
        raise PermissionError("access denied")

    case.Close = deny_close

    with pytest.raises(
        RuntimeError,
        match="HYSYS COM operation failed at close_case",
    ):
        session.close()


def test_session_builds_v15_conversion_reaction_and_reactor_wiring(
    opened_session, tmp_path
):
    session, case, _, _ = opened_session
    session.create_case(tmp_path / "conversion.hsc")
    for component in ("Toluene", "Benzene", "o-Xylene"):
        session.add_component(component)
    session.set_fluid_package("Peng-Robinson")
    feed = session.create_material_stream("Feed")

    reaction_set = session.create_reaction_set("Toluene Reactions")
    session.add_conversion_reaction(
        reaction_set,
        "Toluene-to-o-Xylene",
        {"Toluene": -2.0, "Benzene": 1.0, "o-Xylene": 1.0},
        "Toluene",
        1 / 6,
    )
    reactor = session.create_conversion_reactor("Conversion Reactor")
    session.connect_feed(reactor, "Feed")
    session.attach_reaction_set(reactor, reaction_set)
    session.set_adiabatic(reactor, True)

    manager = case.BasisManager.ReactionPackageManager
    reaction = manager.Reactions.Item("Toluene-to-o-Xylene")
    assert manager.ReactionSets.add_calls == [("Toluene Reactions", "reactionset")]
    assert reaction_set.associated_package is case.fluid_package
    assert manager.Reactions.add_calls == [
        ("Toluene-to-o-Xylene", "conversionrxn")
    ]
    assert reaction.ReactantName.value == ("Toluene", "Benzene", "o-Xylene", "")
    assert reaction.ReactantStoichCoef.value == (-2.0, 1.0, 1.0)
    dedicated = case.BasisManager.ComponentLists.Item("AI HYSYS Components")
    assert reaction.BaseComponent is dedicated.Components.Item("Toluene")
    assert reaction.ConversionCoefficients.value == pytest.approx((100 / 6, 0.0, 0.0))
    assert reaction_set.ActiveReactions.add_calls == [(reaction,)]
    assert case.Flowsheet.Operations.add_calls == [
        ("Conversion Reactor", "conversionreactorop")
    ]
    assert reactor.Feeds.add_calls == [(feed,)]
    assert reactor.ReactionSet is reaction_set
    assert reactor.VapourProduct.name == "Conversion Reactor-Vapour"
    assert reactor.LiquidProduct.name == "Conversion Reactor-Liquid"
    assert reactor.HeatFlow.calls == [("SetValue", 0.0, "kW")]


def test_session_resolves_formula_aliases_before_writing_equilibrium_reaction(
    opened_session, tmp_path
):
    session, case, _, _ = opened_session
    session.create_case(tmp_path / "equilibrium.hsc")
    for component in ("Methane", "Water", "Carbon Monoxide", "Hydrogen"):
        session.add_component(component)
    session.set_fluid_package("Peng-Robinson")
    reaction_set = session.create_equilibrium_reaction_set("Reforming")

    session.add_equilibrium_reaction(
        reaction_set,
        "Steam Reforming",
        {"CH4": -1.0, "H2O": -1.0, "CO": 1.0, "H2": 3.0},
    )

    reaction = case.BasisManager.ReactionPackageManager.Reactions.Item(
        "Steam Reforming"
    )
    assert reaction.ReactantName.value == (
        "Methane",
        "H2O",
        "CO",
        "Hydrogen",
        "",
    )
    assert reaction.ReactantStoichCoef.value == (-1.0, -1.0, 1.0, 3.0)


@pytest.mark.parametrize("corrupt", [False, True])
def test_reaction_readback_controls_coefficient_order(opened_session, tmp_path, corrupt):
    session, case, _, _ = opened_session
    session.create_case(tmp_path / "ordered.hsc")
    for component in ("Methane", "Water", "Carbon Monoxide", "Hydrogen"):
        session.add_component(component)
    session.set_fluid_package("Peng-Robinson")

    class ReorderedNames(ReactionNames):
        @property
        def value(self):
            names = tuple(reversed(self.reactants.items))
            return (*names, "unexpected" if corrupt else "")

    def make_reaction(name, type_name):
        reaction = Reaction(name, type_name)
        reaction.ReactantName = ReorderedNames(reaction.Reactants)
        return reaction

    manager = case.BasisManager.ReactionPackageManager
    manager.Reactions.factory = make_reaction
    reaction_set = session.create_equilibrium_reaction_set("OrderTest")
    stoichiometry = {"CH4": -1.0, "H2O": -1.0, "CO": 1.0, "H2": 3.0}
    if corrupt:
        with pytest.raises(RuntimeError, match="read_reaction_components:R1"):
            session.add_equilibrium_reaction(reaction_set, "R1", stoichiometry)
        assert not reaction_set.ActiveReactions.add_calls
    else:
        session.add_equilibrium_reaction(reaction_set, "R1", stoichiometry)
        reaction = manager.Reactions.Item("R1")
        assert reaction.ReactantStoichCoef.value == (3.0, 1.0, -1.0, -1.0)


def test_session_quits_application_when_file_moniker_created_it(tmp_path):
    seed = tmp_path / "seed.hsc"
    seed.write_bytes(b"verified seed")
    case = FakeCase()

    class OwnedApplication(NamedObject):
        def __init__(self):
            super().__init__("HYSYS")
            self.Version = "Aspen HYSYS Version 15 (41.0)"
            self.quit_calls = 0

        def Quit(self):
            self.quit_calls += 1

    application = OwnedApplication()
    settings = Settings(hysys_base_case_path=seed, hysys_visible=False)
    session = V15CaseSession(
        settings,
        opener=lambda path, progid: (case, application, True),
    )

    session.create_case(tmp_path / "owned.hsc")
    session.close()

    assert case.close_calls == [False]
    assert application.quit_calls == 1
