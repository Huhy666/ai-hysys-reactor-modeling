"""Independent checks over inlet and outlet values read from HYSYS."""

import math
from collections.abc import Mapping
from typing import Any

from app.domain.stoichiometry import _COMPONENT_FORMULAS, _parse_formula


def validate_stream_balance(
    inlets: Mapping[str, dict[str, Any]],
    outlets: Mapping[str, dict[str, Any]],
    *,
    tolerance: float = 0.005,
) -> dict[str, Any]:
    if not inlets or not outlets:
        raise ValueError("mass balance requires real inlet and outlet streams")

    def totals(streams):
        mass = 0.0
        elements: dict[str, float] = {}
        for stream in streams.values():
            molar = stream["molar_flows_kmol_h"]
            masses = stream["mass_flows_kg_h"]
            if not molar or set(molar) != set(masses):
                raise ValueError("incomplete component flows for balance")
            for name, flow in molar.items():
                if not math.isfinite(flow) or flow < 0:
                    raise ValueError(f"invalid molar flow: {name}")
                formula = _COMPONENT_FORMULAS.get(name, name)
                for element, count in _parse_formula(formula).items():
                    elements[element] = elements.get(element, 0.0) + count * flow
            for value in masses.values():
                if not math.isfinite(value) or value < 0:
                    raise ValueError("invalid mass flow")
                mass += value
        return mass, elements

    inlet_mass, inlet_elements = totals(inlets)
    outlet_mass, outlet_elements = totals(outlets)
    if inlet_mass <= 0:
        raise ValueError("positive inlet mass flow required")
    mass_error = abs(outlet_mass - inlet_mass) / inlet_mass
    errors = {
        element: abs(outlet_elements.get(element, 0.0) - inlet_elements.get(element, 0.0))
        / max(abs(inlet_elements.get(element, 0.0)), 1e-9)
        for element in inlet_elements.keys() | outlet_elements.keys()
    }
    report = {
        "passed": mass_error <= tolerance and all(v <= tolerance for v in errors.values()),
        "tolerance": tolerance,
        "inlet_mass_kg_h": inlet_mass,
        "outlet_mass_kg_h": outlet_mass,
        "mass_relative_error": mass_error,
        "element_relative_errors": errors,
    }
    if not report["passed"]:
        raise ValueError(f"independent mass/element balance failed: {report}")
    return report
