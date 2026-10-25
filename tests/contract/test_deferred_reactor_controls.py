from types import SimpleNamespace

import pytest

from app.config import Settings
from app.hysys.ui_fallback import unique
from app.hysys.v15_session import V15CaseSession
from tests.contract.test_solver_readiness import Value


@pytest.mark.parametrize("ui_success", [False, True])
def test_bridge_never_marks_zero_conversion_success(monkeypatch, ui_success):
    clock = [0.0]
    monkeypatch.setattr("app.hysys.v15_session.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("app.hysys.v15_session.time.sleep",
                        lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    reacted = [False]

    class Reactor:
        name = "Conversion Reactor"
        _oleobj_ = object()
        ActAsSeparatorWhenCannotSolve = True
        IsIgnored = False

    reactor = Reactor()
    session = V15CaseSession(Settings(hysys_run_timeout_seconds=5, _env_file=None))
    session.simulation_case = SimpleNamespace(Solver=SimpleNamespace(CanSolve=False))
    session._reactor = reactor
    session._component_names = ["Toluene"]
    session._conversion_targets = {"Toluene": 0.5}
    session._connected_feeds = [SimpleNamespace(ComponentMolarFlow=Value(lambda: [100]))]
    session._output_streams = {"Out": (SimpleNamespace(
        Temperature=Value(lambda: 650), Pressure=Value(lambda: 2500),
        ComponentMolarFlow=Value(lambda: [50 if reacted[0] else 100]),
        ComponentMassFlow=Value(lambda: [4607 if reacted[0] else 9214]),
    ), "gas")}

    # Simulate a server that ignores the COM flag setter while its getter stays True.
    class FixedFlag(Reactor):
        @property
        def ActAsSeparatorWhenCannotSolve(self):
            return True

        @ActAsSeparatorWhenCannotSolve.setter
        def ActAsSeparatorWhenCannotSolve(self, value):
            pass

    session._reactor = FixedFlag()
    bridge_calls = []

    def bridge(filename, name):
        bridge_calls.append((filename, name))
        reacted[0] = ui_success
        return {"success": ui_success, "method": "test_fixture"}

    monkeypatch.setattr("app.hysys.ui_fallback.disable_separator_checkbox", bridge)
    if ui_success:
        session.solve()
        assert session._conversion_checks["Toluene"]["actual_conversion"] == 0.5
    else:
        with pytest.raises(TimeoutError, match="actual_conversion=0.0"):
            session.solve()
        assert session._operator_attention_requested
    assert len(bridge_calls) == 1


@pytest.mark.parametrize("items", [[], [object(), object()]])
def test_ambiguous_ui_target_is_not_clicked(items):
    with pytest.raises(RuntimeError, match="expected one"):
        unique(items, "checkbox")


def test_unique_ui_target_can_be_selected():
    item = object()
    assert unique([item], "checkbox") is item
