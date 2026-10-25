from typing import Protocol

from pydantic import BaseModel, ConfigDict

from app.domain.models import OperatingCaseSpec, ReactorType, SimulationSpec
from app.domain.stoichiometry import check_reaction_balance
from app.domain.units import convert_quantity, normalize_composition
from app.hysys.case_builder import BuiltCase
from app.hysys.interface import ConfiguredReactor, EventSink
from app.runs.models import RunEvent, RunState


class SteamReformingInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feed_temperature_k: float
    feed_pressure_kpa: float
    methane_flow_kmol_h: float
    water_flow_kmol_h: float
    case_temperatures_k: list[float]
    case_pressures_kpa: list[float]
    pressure_drops_kpa: list[float]


class EquilibriumSession(Protocol):
    def create_equilibrium_reaction_set(self, name: str) -> object: ...

    def add_equilibrium_reaction(
        self, reaction_set: object, name: str, stoichiometry: dict[str, float]
    ) -> None: ...

    def create_equilibrium_reactor(self, name: str) -> object: ...

    def connect_feed(self, reactor: object, feed_name: str) -> None: ...

    def attach_reaction_set(self, reactor: object, reaction_set: object) -> None: ...

    def create_energy_stream(self, name: str) -> object: ...

    def connect_energy_stream(self, reactor: object, energy_stream: object) -> None: ...

    def set_outlet_temperature(
        self, reactor: object, value: float, unit: str
    ) -> None: ...

    def set_outlet_pressure(self, reactor: object, value: float, unit: str) -> None: ...

    def set_pressure_drop(self, reactor: object, value: float, unit: str) -> None: ...

    def save_case(self, case_path) -> None: ...


def _required_quantity(value, field: str, unit: str) -> float:
    if value is None:
        raise ValueError(f"{field} is required")
    return convert_quantity(value, unit).value


def validate_steam_reforming_spec(spec: SimulationSpec) -> SteamReformingInputs:
    if spec.reactor_type is not ReactorType.EQUILIBRIUM:
        raise ValueError("steam reforming requires reactor_type=equilibrium")
    if len(spec.feeds) != 1:
        raise ValueError("steam reforming requires exactly one feed")
    if len(spec.operating_cases) != 2:
        raise ValueError("steam reforming comparison requires exactly two operating cases")
    if len(spec.reactions) != 2 or not all(
        reaction.reversible for reaction in spec.reactions
    ):
        raise ValueError("steam reforming requires two reversible reactions")
    if not all(check_reaction_balance(reaction).balanced for reaction in spec.reactions):
        raise ValueError("steam reforming reactions must be element-balanced")

    feed = spec.feeds[0]
    total_flow = _required_quantity(feed.total_flow, "feed.total_flow", "kmol/h")
    composition = normalize_composition(feed.composition)
    try:
        methane_flow = total_flow * composition["Methane"]
        water_flow = total_flow * composition["Water"]
    except KeyError as exc:
        raise ValueError("feed must contain Methane and Water") from exc

    case_temperatures = []
    case_pressures = []
    pressure_drops = []
    for operating_case in spec.operating_cases:
        case_temperatures.append(
            _required_quantity(
                operating_case.outlet_temperature,
                f"operating_cases.{operating_case.name}.outlet_temperature",
                "K",
            )
        )
        case_pressures.append(
            _required_quantity(
                operating_case.outlet_pressure,
                f"operating_cases.{operating_case.name}.outlet_pressure",
                "kPa",
            )
        )
        pressure_drops.append(
            _required_quantity(
                operating_case.pressure_drop,
                f"operating_cases.{operating_case.name}.pressure_drop",
                "kPa",
            )
        )

    return SteamReformingInputs(
        feed_temperature_k=_required_quantity(
            feed.temperature, "feed.temperature", "K"
        ),
        feed_pressure_kpa=_required_quantity(feed.pressure, "feed.pressure", "kPa"),
        methane_flow_kmol_h=methane_flow,
        water_flow_kmol_h=water_flow,
        case_temperatures_k=case_temperatures,
        case_pressures_kpa=case_pressures,
        pressure_drops_kpa=pressure_drops,
    )


def configure_equilibrium_case(
    built_case: BuiltCase,
    spec: SimulationSpec,
    operating_case: OperatingCaseSpec,
    event_sink: EventSink,
) -> ConfiguredReactor:
    if not spec.equilibrium_data_available:
        raise ValueError("HYSYS equilibrium data availability must be confirmed")
    if not spec.reactions or not all(reaction.reversible for reaction in spec.reactions):
        raise ValueError("equilibrium requires explicit reversible reactions")
    if not all(check_reaction_balance(reaction).balanced for reaction in spec.reactions):
        raise ValueError("equilibrium reactions must be element-balanced")
    if operating_case not in spec.operating_cases:
        raise ValueError("operating case does not belong to this specification")
    if len(built_case.feed_names) != 1:
        raise ValueError("equilibrium case requires exactly one feed")

    temperature = _required_quantity(
        operating_case.outlet_temperature, "outlet_temperature", "K"
    )
    pressure = _required_quantity(
        operating_case.outlet_pressure, "outlet_pressure", "kPa"
    )
    pressure_drop = _required_quantity(
        operating_case.pressure_drop, "pressure_drop", "kPa"
    )
    session: EquilibriumSession = built_case.session
    event_sink(
        RunEvent(
            state=RunState.BUILDING_CASE,
            message=f"configuring equilibrium case {operating_case.name}",
        )
    )
    reaction_set = session.create_equilibrium_reaction_set(
        "Equilibrium Reactions"
    )
    for reaction in spec.reactions:
        session.add_equilibrium_reaction(
            reaction_set, reaction.id, reaction.stoichiometry
        )
    reactor = session.create_equilibrium_reactor("Equilibrium Reactor")
    session.connect_feed(reactor, built_case.feed_names[0])
    session.attach_reaction_set(reactor, reaction_set)
    energy_stream = session.create_energy_stream(f"Q-{operating_case.name}")
    session.connect_energy_stream(reactor, energy_stream)
    session.set_outlet_temperature(reactor, temperature, "K")
    session.set_outlet_pressure(reactor, pressure, "kPa")
    session.set_pressure_drop(reactor, pressure_drop, "kPa")
    session.save_case(built_case.case_path)
    return ConfiguredReactor(
        reactor_type=ReactorType.EQUILIBRIUM,
        name="Equilibrium Reactor",
        com_object=reactor,
    )
