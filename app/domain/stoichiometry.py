import re

from app.domain.models import BalanceReport, ReactionSpec

_TOKEN = re.compile(r"([A-Z][a-z]?)(\d*)")
_COMPONENT_FORMULAS = {
    "Methane": "CH4",
    "Water": "H2O",
    "Carbon Monoxide": "CO",
    "Carbon Dioxide": "CO2",
    "Hydrogen": "H2",
    "Toluene": "C7H8",
    "Benzene": "C6H6",
    "o-Xylene": "C8H10",
    "m-Xylene": "C8H10",
    "p-Xylene": "C8H10",
}


def _parse_formula(formula: str) -> dict[str, int]:
    tokens = list(_TOKEN.finditer(formula))
    if not tokens or "".join(match.group(0) for match in tokens) != formula:
        raise ValueError(f"unsupported formula: {formula}")
    counts: dict[str, int] = {}
    for match in tokens:
        element = match.group(1)
        count = int(match.group(2) or "1")
        counts[element] = counts.get(element, 0) + count
    return counts


def check_reaction_balance(reaction: ReactionSpec) -> BalanceReport:
    residuals: dict[str, float] = {}
    try:
        for formula, coefficient in reaction.stoichiometry.items():
            formula = _COMPONENT_FORMULAS.get(formula, formula)
            for element, count in _parse_formula(formula).items():
                residuals[element] = residuals.get(element, 0.0) + coefficient * count
    except ValueError as exc:
        return BalanceReport(supported=False, balanced=False, message=str(exc))

    mismatches = {
        element: int(value) if float(value).is_integer() else value
        for element, value in sorted(residuals.items())
        if abs(value) > 1e-9
    }
    return BalanceReport(
        supported=True,
        balanced=not mismatches,
        element_residuals=mismatches,
        message="" if not mismatches else "reaction is not element-balanced",
    )
