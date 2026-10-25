import pytest

from app.domain.demo_specs import generalization_specs
from app.domain.reactor_selection import select_reactor
from app.domain.stoichiometry import check_reaction_balance


@pytest.mark.parametrize("name", ["shift", "reverse_shift", "methanation"])
def test_additional_inputs_use_generic_rules_and_balanced_reactions(name):
    spec = generalization_specs(confirmed=True)[name]
    spec.reactor_type = None
    decision = select_reactor(spec)
    assert decision.reactor_type.value == "conversion"
    assert decision.reason_codes == ["KNOWN_CONVERSION"]
    assert not decision.blocking_issues
    assert all(check_reaction_balance(reaction).balanced for reaction in spec.reactions)
