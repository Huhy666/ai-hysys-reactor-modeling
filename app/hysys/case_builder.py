from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import SimulationSpec, StreamSpec
from app.domain.units import convert_quantity, normalize_composition
from app.hysys.component_mapping import resolve_component
from app.hysys.interface import EventSink
from app.runs.models import RunEvent, RunState


class CaseSession(Protocol):
    def create_case(self, case_path: Path) -> object: ...

    def add_component(self, name: str) -> None: ...

    def set_fluid_package(self, name: str) -> None: ...

    def create_material_stream(self, name: str) -> object: ...

    def set_stream_temperature(
        self, stream: object, value: float, unit: str
    ) -> None: ...

    def set_stream_pressure(self, stream: object, value: float, unit: str) -> None: ...

    def set_stream_flow(self, stream: object, value: float, unit: str) -> None: ...

    def set_stream_composition(
        self, stream: object, composition: dict[str, float]
    ) -> None: ...

    def save_case(self, case_path: Path) -> None: ...


class BuiltCase(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    session: Any
    simulation_case: Any
    case_path: Path
    hysys_version: str | None = None
    component_names: list[str] = Field(default_factory=list)
    fluid_package: str
    feed_names: list[str] = Field(default_factory=list)


class PreparedFeed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    temperature_k: float | None = None
    pressure_kpa: float | None = None
    flow_value: float | None = None
    flow_unit: str | None = None
    composition: dict[str, float]


def _resolved_name(name: str) -> str:
    match = resolve_component(name)
    if match.hysys_name is None or match.requires_confirmation:
        raise ValueError(f"component requires confirmation: {name}")
    return match.hysys_name


def _prepare_feed(feed: StreamSpec) -> PreparedFeed:
    temperature = (
        convert_quantity(feed.temperature, "K") if feed.temperature is not None else None
    )
    pressure = convert_quantity(feed.pressure, "kPa") if feed.pressure is not None else None

    flow_value = None
    flow_unit = None
    if feed.total_flow is not None:
        expected_unit = {"molar": "kmol/h", "mass": "kg/h"}.get(feed.flow_basis or "")
        if expected_unit is None:
            raise ValueError("flow_basis must be 'molar' or 'mass'")
        flow = convert_quantity(feed.total_flow, expected_unit)
        if flow.value < 0:
            raise ValueError("flow cannot be negative")
        flow_value = flow.value
        flow_unit = flow.unit

    resolved_composition: dict[str, float] = {}
    for component, fraction in feed.composition.items():
        hysys_name = _resolved_name(component)
        resolved_composition[hysys_name] = (
            resolved_composition.get(hysys_name, 0.0) + fraction
        )
    composition = normalize_composition(resolved_composition)
    return PreparedFeed(
        name=feed.name,
        temperature_k=temperature.value if temperature else None,
        pressure_kpa=pressure.value if pressure else None,
        flow_value=flow_value,
        flow_unit=flow_unit,
        composition=composition,
    )


def build_base_case(
    session: CaseSession,
    spec: SimulationSpec,
    case_path: Path,
    event_sink: EventSink,
) -> BuiltCase:
    if not spec.fluid_package:
        raise ValueError("an explicit fluid package is required")

    resolved_components: list[str] = []
    for component in spec.components:
        name = _resolved_name(component.hysys_name or component.user_name)
        if name not in resolved_components:
            resolved_components.append(name)
    prepared_feeds = [_prepare_feed(feed) for feed in spec.feeds]
    for feed in prepared_feeds:
        for component in feed.composition:
            if component not in resolved_components:
                resolved_components.append(component)

    resolved_case_path = Path(case_path).resolve()
    if resolved_case_path.suffix.lower() != ".hsc":
        raise ValueError("case path must use the .hsc extension")
    resolved_case_path.parent.mkdir(parents=True, exist_ok=True)

    event_sink(RunEvent(state=RunState.BUILDING_CASE, message="building HYSYS base case"))
    simulation_case = session.create_case(resolved_case_path)
    for component in resolved_components:
        session.add_component(component)
    session.set_fluid_package(spec.fluid_package)

    for feed in prepared_feeds:
        stream = session.create_material_stream(feed.name)
        if feed.temperature_k is not None:
            session.set_stream_temperature(stream, feed.temperature_k, "K")
        if feed.pressure_kpa is not None:
            session.set_stream_pressure(stream, feed.pressure_kpa, "kPa")
        if feed.flow_value is not None and feed.flow_unit is not None:
            session.set_stream_flow(stream, feed.flow_value, feed.flow_unit)
        session.set_stream_composition(stream, feed.composition)

    session.save_case(resolved_case_path)
    return BuiltCase(
        session=session,
        simulation_case=simulation_case,
        case_path=resolved_case_path,
        hysys_version=getattr(session, "version", None),
        component_names=resolved_components,
        fluid_package=spec.fluid_package,
        feed_names=[feed.name for feed in prepared_feeds],
    )
