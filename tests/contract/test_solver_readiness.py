import json
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.hysys.v15_session import V15CaseSession


class Value:
    IsKnown = True

    def __init__(self, getter):
        self.getter = getter

    def GetValue(self, unit):
        return self.getter()

    def GetValues(self, unit):
        return self.getter()


@pytest.mark.parametrize('updates', [True, False])
def test_solver_rejects_stale_feed_until_conversion_and_stability(monkeypatch, updates, tmp_path):
    clock = [0.0]
    monkeypatch.setattr('app.hysys.v15_session.time.monotonic', lambda: clock[0])
    monkeypatch.setattr('app.hysys.v15_session.time.sleep',
                        lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    session = V15CaseSession(Settings(hysys_run_timeout_seconds=10))
    session.simulation_case = SimpleNamespace(Solver=SimpleNamespace(CanSolve=False))
    session._component_names = ['Toluene']
    session._conversion_targets = {'Toluene': 0.5}
    session._connected_feeds = [SimpleNamespace(ComponentMolarFlow=Value(lambda: [100.0]))]
    stream = SimpleNamespace(
        Temperature=Value(lambda: 651.4), Pressure=Value(lambda: 2500),
        ComponentMolarFlow=Value(lambda: [50.0 if updates and clock[0] >= 3 else 100.0]),
        ComponentMassFlow=Value(lambda: [4607.0 if updates and clock[0] >= 3 else 9214.0]),
    )
    session._output_streams = {'out': (stream, 'gas')}
    if updates:
        session.solve()
        assert clock[0] >= 4.0
    else:
        session._diagnostic_path = tmp_path / "solver-diagnostics.json"
        with pytest.raises(TimeoutError):
            session.solve()
        diagnostic = json.loads(session._diagnostic_path.read_text(encoding="utf-8"))
        assert diagnostic["conversion_checks"]["Toluene"]["actual_conversion"] == 0
        assert diagnostic["conversion_checks"]["Toluene"]["target_conversion"] == 0.5
