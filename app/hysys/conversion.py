from math import isclose
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from app.domain.models import ReactionSpec, ReactorType, SimulationSpec
from app.domain.stoichiometry import check_reaction_balance
from app.hysys.case_builder import BuiltCase
from app.hysys.component_mapping import resolve_component
from app.hysys.interface import ConfiguredReactor, EventSink
from app.runs.models import RunEvent, RunState

TOLUENE_MOLECULAR_WEIGHT_KG_PER_KMOL = 92.14
XYLENE_ISOMERS = ("o-Xylene", "m-Xylene", "p-Xylene")


class TolueneReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feed_toluene_kmol_h: float
    reacted_toluene_kmol_h: float
    unreacted_toluene_kmol_h: float
    benzene_kmol_h: float
    total_xylene_kmol_h: float


class ConversionSession(Protocol):
    def create_reaction_set(self, name: str) -> object: ...

    def add_conversion_reaction(
        self,
        reaction_set: object,
        name: str,
        stoichiometry: dict[str, float],
        base_component: str,
        conversion: float,
    ) -> None: ...

    def create_conversion_reactor(self, name: str) -> object: ...

    def connect_feed(self, reactor: object, feed_name: str) -> None: ...

    def attach_reaction_set(self, reactor: object, reaction_set: object) -> None: ...

    def set_adiabatic(self, reactor: object, enabled: bool) -> None: ...

    def save_case(self, case_path) -> None: ...


def calculate_toluene_reference(
    feed_toluene_kg_h: float,
    conversion: float,
) -> TolueneReference:
    if feed_toluene_kg_h < 0:
        raise ValueError("toluene feed cannot be negative")
    if not 0 <= conversion <= 1:
        raise ValueError("conversion must be between 0 and 1")
    feed = feed_toluene_kg_h / TOLUENE_MOLECULAR_WEIGHT_KG_PER_KMOL
    reacted = feed * conversion
    extent = reacted / 2.0
    return TolueneReference(
        feed_toluene_kmol_h=feed,
        reacted_toluene_kmol_h=reacted,
        unreacted_toluene_kmol_h=feed - reacted,
        benzene_kmol_h=extent,
        total_xylene_kmol_h=extent,
    )


def _explicit_selectivities(spec: SimulationSpec) -> dict[str, float] | None:
    selectivities: dict[str, float] = {}
    for reaction in spec.reactions:
        isomers = [name for name in XYLENE_ISOMERS if name in reaction.stoichiometry]
        if len(isomers) == 1 and reaction.selectivity is not None:
            selectivities[isomers[0]] = reaction.selectivity
    if not selectivities:
        return None
    if set(selectivities) != set(XYLENE_ISOMERS):
        raise ValueError("selectivities must cover all three xylene isomers")
    if not isclose(sum(selectivities.values()), 1.0, abs_tol=1e-9):
        raise ValueError("xylene selectivities must sum to 1")
    return selectivities


def _equal_split_confirmed(spec: SimulationSpec) -> bool:
    markers = ("等选择性", "等比例", "equal split", "equal selectivity")
    return any(
        assumption.confirmed
        and any(marker in assumption.text.casefold() for marker in markers)
        for assumption in spec.assumptions
    )


def build_toluene_parallel_reactions(spec: SimulationSpec) -> list[ReactionSpec]:
    total_conversion = spec.known_conversion
    if total_conversion is None:
        raise ValueError("total toluene conversion is required")
    selectivities = _explicit_selectivities(spec)
    if selectivities is None:
        if not _equal_split_confirmed(spec):
            raise ValueError("xylene selectivities require confirmation")
        selectivities = {name: 1.0 / 3.0 for name in XYLENE_ISOMERS}

    reactions = []
    for isomer in XYLENE_ISOMERS:
        selectivity = selectivities[isomer]
        reactions.append(
            ReactionSpec(
                id=f"Toluene-to-{isomer}",
                equation=f"2 Toluene -> Benzene + {isomer}",
                stoichiometry={"Toluene": -2.0, "Benzene": 1.0, isomer: 1.0},
                conversion=total_conversion * selectivity,
                selectivity=selectivity,
            )
        )
    return reactions


def configure_conversion_case(
    built_case: BuiltCase,
    spec: SimulationSpec,
    event_sink: EventSink,
) -> ConfiguredReactor:
    if spec.reactor_type is not ReactorType.CONVERSION:
        raise ValueError("conversion builder requires reactor_type=conversion")
    aromatic_components = {
        "Toluene",
        "Benzene",
        *XYLENE_ISOMERS,
    }
    if len(built_case.feed_names) != 1:
        raise ValueError("conversion case requires exactly one feed")

    is_toluene = aromatic_components <= set(built_case.component_names) and all(
        reaction.stoichiometry.get("Toluene") == -2
        and reaction.stoichiometry.get("Benzene") == 1
        and set(reaction.stoichiometry) <= aromatic_components
        and sum(reaction.stoichiometry.get(name, 0) for name in XYLENE_ISOMERS) == 1
        for reaction in spec.reactions
    )
    reactions = build_toluene_parallel_reactions(spec) if is_toluene else spec.reactions
    if not reactions:
        raise ValueError("conversion requires explicit reactions")
    prepared = []
    targets: dict[str, float] = {}
    for reaction in reactions:
        stoichiometry = {}
        for name, coefficient in reaction.stoichiometry.items():
            match = resolve_component(name)
            if match.hysys_name is None or match.requires_confirmation:
                raise ValueError(f"reaction component requires confirmation: {name}")
            stoichiometry[match.hysys_name] = (
                stoichiometry.get(match.hysys_name, 0.0) + coefficient
            )
        normalized = reaction.model_copy(update={"stoichiometry": stoichiometry})
        if not check_reaction_balance(normalized).balanced:
            raise ValueError(f"reaction is not element-balanced: {reaction.id}")
        reactants = [name for name, value in stoichiometry.items() if value < 0]
        base = reaction.base_component
        if base is not None:
            base = resolve_component(base).hysys_name
        elif len(reactants) == 1:
            base = reactants[0]
        if base not in reactants:
            raise ValueError(f"explicit base_component required for {reaction.id}")
        conversion = reaction.conversion
        if conversion is None and len(reactions) == 1:
            conversion = spec.known_conversion
        if conversion is None:
            raise ValueError(f"explicit conversion required for {reaction.id}")
        targets[base] = targets.get(base, 0.0) + conversion
        if targets[base] > 1.0 + 1e-9:
            raise ValueError(f"total conversion exceeds 100% for {base}")
        prepared.append((reaction.id, stoichiometry, base, conversion))
    for _, stoichiometry, _, _ in prepared:
        if any(stoichiometry.get(base, 0.0) > 0 for base in targets):
            raise ValueError("coupled conversion reactions require an explicit staged model")
    session: ConversionSession = built_case.session
    event_sink(
        RunEvent(
            state=RunState.BUILDING_CASE,
            message="configuring conversion reactor",
        )
    )
    reaction_set = session.create_reaction_set("Conversion Reactions")
    for name, stoichiometry, base, conversion in prepared:
        session.add_conversion_reaction(
            reaction_set,
            name,
            stoichiometry,
            base,
            conversion,
        )
    reactor = session.create_conversion_reactor("Conversion Reactor")
    session.connect_feed(reactor, built_case.feed_names[0])
    session.attach_reaction_set(reactor, reaction_set)
    session.set_adiabatic(reactor, True)
    session.save_case(built_case.case_path)
    return ConfiguredReactor(
        reactor_type=ReactorType.CONVERSION,
        name="Conversion Reactor",
        com_object=reactor,
    )
