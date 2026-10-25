import pytest

from app.domain.models import Quantity
from app.domain.units import convert_quantity, normalize_composition


@pytest.mark.parametrize(
    ("value", "unit", "target", "expected"),
    [
        (520.0, "degC", "K", 793.15),
        (380.0, "C", "K", 653.15),
        (380.0, "°C", "K", 653.15),
        (380.0, "℃", "K", 653.15),
        (653.15, "K", "C", 380.0),
        (380.0, "C", "degC", 380.0),
        (13.5, "bar", "kPa", 1350.0),
        (13.5, "bar(a)", "kPa", 1350.0),
        (13.5, "bara", "kPa", 1350.0),
        (2.5, "MPa", "kPa", 2500.0),
    ],
)
def test_convert_quantity_uses_explicit_absolute_units(value, unit, target, expected):
    converted = convert_quantity(Quantity(value=value, unit=unit), target)

    assert converted.value == pytest.approx(expected)
    assert converted.unit == target


@pytest.mark.parametrize("unit", ["barg", "bar(g)", "kPag", "kPa(g)"])
def test_convert_quantity_rejects_gauge_pressure(unit):
    with pytest.raises(ValueError, match="gauge pressure"):
        convert_quantity(Quantity(value=1.0, unit=unit), "kPa")


def test_normalize_composition_rejects_negative_fraction():
    with pytest.raises(ValueError, match="negative"):
        normalize_composition({"Methane": 1.0, "Water": -0.1})


@pytest.mark.parametrize("unit", [
    "kPa(abs)", "kPa (abs)", " kPa ", "kPa（a）", "kPa absolute",
    "kPa绝压", "kPa(绝压)", "kpa(a)", "KPA", "kPa(a)", "kPaa",
])
def test_absolute_pressure_spelling_variants(unit):
    assert convert_quantity(Quantity(value=2500, unit=unit), "kPa").value == 2500


@pytest.mark.parametrize("unit", ["kPa (g)", "kPa(gauge)", "kPa 表压", "MPa（g）"])
def test_spelling_normalization_does_not_turn_gauge_pressure_into_absolute(unit):
    with pytest.raises(ValueError, match="gauge pressure"):
        convert_quantity(Quantity(value=1, unit=unit), "kPa")


@pytest.mark.parametrize("unit", ["mPa", "kPa/unknown", "kPa(abs)(g)"])
def test_unknown_or_conflicting_pressure_units_are_not_guessed(unit):
    with pytest.raises(ValueError, match="unsupported unit conversion"):
        convert_quantity(Quantity(value=1, unit=unit), "kPa")


def test_target_gauge_pressure_is_also_rejected():
    with pytest.raises(ValueError, match="gauge pressure"):
        convert_quantity(Quantity(value=1, unit="bar"), "kPa(g)")


@pytest.mark.parametrize(("unit", "target", "expected"), [
    ("° C", "K", 653.15), ("℃", "K", 653.15),
    ("MPa(abs)", "kPa", 380000), ("kg / hr", "kg/h", 380),
    ("kmol/hr", "kmol/h", 380),
])
def test_other_explicit_unit_variants(unit, target, expected):
    assert convert_quantity(Quantity(value=380, unit=unit), target).value == pytest.approx(expected)
