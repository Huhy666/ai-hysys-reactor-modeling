import re
import unicodedata
from collections.abc import Mapping

from app.domain.models import Quantity

TEMPERATURE_UNIT_ALIASES = {"C": "degC", "°C": "degC", "℃": "degC"}

ABSOLUTE_PRESSURE_UNIT_ALIASES = {
    "bar(a)": "bar",
    "bara": "bar",
    "kPa(a)": "kPa",
    "kPaa": "kPa",
    "MPa(a)": "MPa",
    "MPaa": "MPa",
}
GAUGE_PRESSURE_UNITS = {
    "barg",
    "bar(g)",
    "kPag",
    "kPa(g)",
    "MPag",
    "MPa(g)",
}


def canonical_unit(unit: str) -> str:
    """Accept explicit spelling variants without guessing a pressure reference."""
    value = unicodedata.normalize("NFKC", unit).strip()
    compact = re.sub(r"\s+", "", value)
    pressure = re.fullmatch(
        r"(kPa|KPA|kpa|Kpa|MPa|MPA|Mpa|Pa|PA|pa|bar|Bar|BAR)(.*)", compact,
    )
    if pressure:
        base, suffix = pressure.groups()
        canonical = {"kpa": "kPa", "mpa": "MPa", "pa": "Pa", "bar": "bar"}[base.lower()]
        suffix = suffix.casefold()
        if suffix in {"g", "(g)", "gauge", "(gauge)", "表压", "(表压)"}:
            raise ValueError("gauge pressure requires an atmospheric-pressure reference")
        if suffix in {"", "a", "(a)", "abs", "(abs)", "absolute", "(absolute)",
                      "绝压", "(绝压)", "绝对压力", "(绝对压力)"}:
            return canonical
    temperatures = {
        "c": "degC", "°c": "degC", "degc": "degC", "celsius": "degC",
        "摄氏度": "degC", "k": "K", "kelvin": "K", "开尔文": "K",
    }
    if compact.casefold() in temperatures:
        return temperatures[compact.casefold()]
    flows = {
        "kg/h": "kg/h", "kg/hr": "kg/h", "kg/hour": "kg/h",
        "kmol/h": "kmol/h", "kmol/hr": "kmol/h", "kmol/hour": "kmol/h",
        "kgmole/h": "kmol/h", "kgmol/h": "kmol/h",
    }
    return flows.get(compact, compact)


def convert_quantity(quantity: Quantity, target_unit: str) -> Quantity:
    source_unit = quantity.unit
    source = canonical_unit(source_unit)
    target = canonical_unit(target_unit)
    pressure_factors = {"Pa": 0.001, "kPa": 1.0, "MPa": 1000.0, "bar": 100.0}
    if source in pressure_factors and target in pressure_factors:
        return Quantity(
            value=quantity.value * pressure_factors[source] / pressure_factors[target],
            unit=target_unit, source=quantity.source,
        )
    if source == target:
        return Quantity(
            value=quantity.value,
            unit=target_unit,
            source=quantity.source,
        )

    conversions = {
        ("degC", "K"): lambda value: value + 273.15,
        ("K", "degC"): lambda value: value - 273.15,
        ("bar", "kPa"): lambda value: value * 100.0,
        ("MPa", "kPa"): lambda value: value * 1000.0,
        ("Pa", "kPa"): lambda value: value / 1000.0,
        ("kPa", "bar"): lambda value: value / 100.0,
        ("kPa", "MPa"): lambda value: value / 1000.0,
    }
    converter = conversions.get((source, target))
    if converter is None:
        raise ValueError(
            f"unsupported unit conversion: {source_unit!r} -> {target_unit!r}"
        )
    return Quantity(value=converter(quantity.value), unit=target_unit, source=quantity.source)


def normalize_composition(composition: Mapping[str, float]) -> dict[str, float]:
    if not composition:
        raise ValueError("composition cannot be empty")
    if any(value < 0 for value in composition.values()):
        raise ValueError("composition contains a negative fraction")
    total = sum(composition.values())
    if total <= 0:
        raise ValueError("composition total must be positive")
    return {component: value / total for component, value in composition.items()}
