import pytest

from app.domain.models import ReactionSpec
from app.domain.stoichiometry import check_reaction_balance


@pytest.mark.parametrize(
    ("stoichiometry", "balanced", "residuals"),
    [
        ({"Methane": -1, "Water": -1, "Carbon Monoxide": 1, "Hydrogen": 3}, True, {}),
        ({"Carbon Monoxide": -1, "Water": -1, "Carbon Dioxide": 1, "Hydrogen": 1}, True, {}),
        ({"Methane": -1, "Water": -1, "Carbon Monoxide": 1, "Hydrogen": 1}, False, {"H": -4}),
    ],
)
def test_balance_checks_named_reaction_components(stoichiometry, balanced, residuals):
    reaction = ReactionSpec(id="R1", equation="diagnostic", stoichiometry=stoichiometry)

    report = check_reaction_balance(reaction)

    assert report.supported is True
    assert report.balanced is balanced
    assert report.element_residuals == residuals


@pytest.mark.parametrize(
    ("equation", "stoichiometry"),
    [
        ("CH4 + H2O <=> CO + 3H2", {"CH4": -1, "H2O": -1, "CO": 1, "H2": 3}),
        ("CO + H2O <=> CO2 + H2", {"CO": -1, "H2O": -1, "CO2": 1, "H2": 1}),
        ("2C7H8 -> C6H6 + C8H10", {"C7H8": -2, "C6H6": 1, "C8H10": 1}),
    ],
)
def test_check_reaction_balance_accepts_balanced_reactions(equation, stoichiometry):
    reaction = ReactionSpec(
        id="R1",
        equation=equation,
        stoichiometry=stoichiometry,
        reversible="<=>" in equation,
    )

    report = check_reaction_balance(reaction)

    assert report.supported is True
    assert report.balanced is True
    assert report.element_residuals == {}


def test_check_reaction_balance_reports_mismatched_element():
    reaction = ReactionSpec(
        id="bad",
        equation="CH4 + H2O -> CO + H2",
        stoichiometry={"CH4": -1, "H2O": -1, "CO": 1, "H2": 1},
    )

    report = check_reaction_balance(reaction)

    assert report.balanced is False
    assert report.element_residuals == {"H": -4}


def test_check_reaction_balance_marks_ionic_formula_unsupported():
    reaction = ReactionSpec(
        id="ionic",
        equation="Na+ -> Na+",
        stoichiometry={"Na+": -1, "Na": 1},
    )

    report = check_reaction_balance(reaction)

    assert report.supported is False
    assert report.balanced is False
    assert "unsupported formula" in report.message
