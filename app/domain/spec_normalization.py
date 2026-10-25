"""Resolve a declared xylene product group only after operator confirmation."""

from math import isclose

from app.domain.models import DraftSimulationSpec, ReactionSpec, ReactorType
from app.hysys.component_mapping import MatchStatus, resolve_component

XYLENES = ("o-Xylene", "m-Xylene", "p-Xylene")


def expand_confirmed_xylene_group(spec: DraftSimulationSpec):
    result = spec.model_copy(deep=True)
    if (spec.reactor_type not in {None, ReactorType.CONVERSION}
            or len(spec.reactions) != 1 or spec.kinetics is not None):
        return result
    equal = any(
        item.confirmed and any(marker in item.text.casefold() for marker in (
            "等选择性", "等比例", "equal split", "equal selectivity",
        )) for item in spec.assumptions
    )
    declared = {
        resolve_component(item.hysys_name or item.user_name).hysys_name
        for item in spec.components
    }
    if not equal or not set(XYLENES) <= declared:
        return result

    def canonical(name):
        match = resolve_component(name)
        return match.hysys_name or name

    expanded = []
    changed = False
    for reaction in spec.reactions:
        stoich = {}
        groups = []
        for name, coefficient in reaction.stoichiometry.items():
            match = resolve_component(name)
            if match.status is MatchStatus.AMBIGUOUS and set(match.candidates) == set(XYLENES):
                groups.append((name, coefficient))
            else:
                key = canonical(name)
                stoich[key] = stoich.get(key, 0.0) + coefficient
        conversion = spec.known_conversion
        if conversion is None:
            conversion = reaction.conversion
        if (len(groups) != 1 or groups[0][1] != 1
                or stoich != {"Toluene": -2, "Benzene": 1} or conversion is None
                or (reaction.conversion is not None
                    and not isclose(conversion, reaction.conversion, abs_tol=1e-9))
                or (reaction.base_component and canonical(reaction.base_component) != "Toluene")):
            expanded.append(reaction.model_copy(deep=True))
            continue
        changed = True
        for isomer in XYLENES:
            expanded.append(ReactionSpec(
                id=f"{reaction.id}-{isomer}", equation=f"2 Toluene -> Benzene + {isomer}",
                stoichiometry={**stoich, isomer: 1.0}, reversible=reaction.reversible,
                conversion=conversion / 3, selectivity=1 / 3, base_component="Toluene",
            ))
        if result.known_conversion is None:
            result.known_conversion = conversion
    if not changed:
        return result
    result.reactions = expanded
    # Retain the unresolved name if any feed or remaining reaction still uses it.
    references = {name for feed in result.feeds for name in feed.composition}
    references.update(name for reaction in expanded for name in reaction.stoichiometry)
    result.components = [
        item for item in result.components
        if resolve_component(item.hysys_name or item.user_name).status is not MatchStatus.AMBIGUOUS
        or item.user_name in references or item.hysys_name in references
    ]
    return result
