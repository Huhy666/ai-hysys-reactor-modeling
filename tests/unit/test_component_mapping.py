import pytest

from app.hysys.component_mapping import MatchStatus, resolve_component


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("甲烷", "Methane"),
        ("CH4", "Methane"),
        ("水蒸气", "Water"),
        ("H2O", "Water"),
        ("一氧化碳", "Carbon Monoxide"),
        ("CO2", "Carbon Dioxide"),
        ("氢气", "Hydrogen"),
        ("甲苯", "Toluene"),
        ("苯", "Benzene"),
        ("邻二甲苯", "o-Xylene"),
        ("m-xylene", "m-Xylene"),
        ("对二甲苯", "p-Xylene"),
    ],
)
def test_resolves_required_chinese_formula_and_english_aliases(query, expected):
    match = resolve_component(query)

    assert match.status in {MatchStatus.EXACT, MatchStatus.ALIAS}
    assert match.hysys_name == expected
    assert match.requires_confirmation is False


def test_exact_hysys_name_wins_before_alias_matching():
    match = resolve_component("o-Xylene")

    assert match.status is MatchStatus.EXACT
    assert match.hysys_name == "o-Xylene"


@pytest.mark.parametrize("query", ["二甲苯", "xylene", "C8H10"])
def test_ambiguous_xylene_requires_user_confirmation(query):
    match = resolve_component(query)

    assert match.status is MatchStatus.AMBIGUOUS
    assert match.hysys_name is None
    assert match.candidates == ["o-Xylene", "m-Xylene", "p-Xylene"]
    assert match.requires_confirmation is True


def test_unknown_component_is_not_fuzzy_auto_selected():
    match = resolve_component("methan")

    assert match.status is MatchStatus.NOT_FOUND
    assert match.hysys_name is None
    assert match.candidates == []
    assert match.requires_confirmation is True
