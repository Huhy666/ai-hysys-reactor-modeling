import math
from collections.abc import Mapping
from typing import Any

from app.domain.models import SimulationResult, SimulationSpec
from app.hysys.case_builder import BuiltCase


def _finite(value: Any, field: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"invalid HYSYS result at {field}: expected a number")
    normalized = float(value)
    if not math.isfinite(normalized) or (nonnegative and normalized < 0):
        raise ValueError(f"invalid HYSYS result at {field}: {value}")
    return normalized


def _validate_mapping_values(
    values: Any, field: str, *, nonnegative: bool = True
) -> dict[str, float]:
    if not isinstance(values, Mapping):
        raise ValueError(f"invalid HYSYS result at {field}: expected a mapping")
    return {
        str(name): _finite(value, f"{field}.{name}", nonnegative=nonnegative)
        for name, value in values.items()
    }


def _normalize_stream(name: str, stream: Any) -> dict[str, Any]:
    if not isinstance(stream, Mapping):
        raise ValueError(f"invalid HYSYS result at streams.{name}")
    normalized = dict(stream)
    normalized["temperature_k"] = _finite(
        stream.get("temperature_k"), f"streams.{name}.temperature_k", nonnegative=True
    )
    normalized["pressure_kpa"] = _finite(
        stream.get("pressure_kpa"), f"streams.{name}.pressure_kpa", nonnegative=True
    )
    for field in ("mole_fractions", "molar_flows_kmol_h", "mass_flows_kg_h"):
        normalized[field] = _validate_mapping_values(
            stream.get(field), f"streams.{name}.{field}"
        )
    if not isinstance(stream.get("phase"), str) or not stream["phase"]:
        raise ValueError(f"invalid HYSYS result at streams.{name}.phase")
    if stream.get("composition_basis") not in {"mole", "mass"}:
        raise ValueError(f"invalid HYSYS result at streams.{name}.composition_basis")
    return normalized


def read_result(built_case: BuiltCase, spec: SimulationSpec) -> SimulationResult:
    raw = built_case.session.read_case_result(built_case, spec)
    if not isinstance(raw, Mapping):
        raise ValueError("invalid HYSYS result: expected a mapping")
    converged = raw.get("converged")
    if not isinstance(converged, bool):
        raise ValueError("missing or invalid HYSYS convergence status")
    streams = raw.get("streams")
    if not isinstance(streams, Mapping):
        raise ValueError("invalid HYSYS result at streams")
    normalized_streams = {
        str(name): _normalize_stream(str(name), stream) for name, stream in streams.items()
    }
    duty = raw.get("reactor_duty_kw")
    normalized_duty = None if duty is None else _finite(duty, "reactor_duty_kw")
    warnings = raw.get("warnings", [])
    if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
        raise ValueError("invalid HYSYS result at warnings")
    return SimulationResult(
        run_id=built_case.case_path.parent.name,
        source="hysys",
        converged=converged,
        hysys_version=built_case.hysys_version,
        case_paths=[str(built_case.case_path.resolve())],
        streams=normalized_streams,
        reactor_duty_kw=normalized_duty,
        warnings=warnings,
        validation=raw.get("validation", {}),
        inlet_streams=raw.get("inlet_streams", {}),
    )
