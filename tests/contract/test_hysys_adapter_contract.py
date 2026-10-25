from pathlib import Path

import pytest

from app.domain.models import Assumption
from app.hysys.fake_adapter import FakeHysysAdapter
from app.hysys.interface import HysysCapabilities
from app.hysys.v15_adapter import V15HysysAdapter
from app.runs.models import RunEvent, RunState
from tests.unit.test_run_repository import _spec
from tests.unit.test_steam_reforming_spec import steam_reforming_spec
from tests.unit.test_toluene_mass_balance import _spec as toluene_spec


def test_fake_adapter_emits_stages_and_keeps_artifacts_in_run_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_dir = tmp_path / "runs" / "fake-run"
    events: list[RunEvent] = []
    adapter = FakeHysysAdapter()

    capabilities = adapter.probe()
    session = adapter.start_owned_session()
    result = adapter.build_and_run(_spec(), run_dir, events.append)
    adapter.close_owned_session()

    assert isinstance(capabilities, HysysCapabilities)
    assert capabilities.dispatch is True
    assert session.owned_by_app is True
    assert [event.state for event in events] == [
        RunState.CONNECTING,
        RunState.BUILDING_CASE,
        RunState.SOLVING,
        RunState.READING_RESULTS,
        RunState.VALIDATING,
    ]
    assert result.source == "fake"
    assert result.case_paths
    assert all(Path(path).is_relative_to(run_dir) for path in result.case_paths)
    files = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert files
    assert all(path.is_relative_to(run_dir) for path in files)


def test_fake_adapter_is_forbidden_in_production():
    with pytest.raises(ValueError, match="production"):
        FakeHysysAdapter(production_mode=True)


def test_v15_adapter_never_closes_unowned_application():
    class ExternalApplication:
        def __init__(self):
            self.quit_calls = 0

        def Quit(self):
            self.quit_calls += 1

    application = ExternalApplication()
    adapter = V15HysysAdapter(application=application, owned_by_app=False)

    adapter.close_owned_session()

    assert application.quit_calls == 0
    assert adapter.owned_by_app is False


def test_v15_adapter_defers_application_start_until_seed_case_open(monkeypatch):
    def forbidden_dispatch(progid):
        raise AssertionError(f"unexpected eager dispatch: {progid}")

    monkeypatch.setattr("app.hysys.v15_adapter._dispatch_new", forbidden_dispatch)
    adapter = V15HysysAdapter()

    session = adapter.start_owned_session()
    adapter.close_owned_session()

    assert session.owned_by_app is True
    assert session.version is None
    assert adapter.owned_by_app is False


def test_seed_case_satisfies_case_creation_capability():
    capabilities = HysysCapabilities(
        python_architecture="64bit",
        progid="HYSYS.Application",
        architecture_compatible=True,
        progid_configured=True,
        dispatch=True,
        version_read=True,
        blank_case=False,
        seed_case=True,
        stream_round_trip=True,
        case_save=True,
    )

    assert capabilities.all_required is True


class RecordingRunSession:
    version = "Aspen HYSYS Version 15 (41.0)"

    def __init__(self, settings, *, application=None):
        self.settings = settings
        self.application = application
        self.calls = []

    def create_case(self, case_path):
        case_path = Path(case_path)
        case_path.parent.mkdir(parents=True, exist_ok=True)
        case_path.write_bytes(b"hysys case")
        self.calls.append(("create_case", case_path))
        return object()

    def add_component(self, name):
        self.calls.append(("add_component", name))

    def set_fluid_package(self, name):
        self.calls.append(("set_fluid_package", name))

    def create_material_stream(self, name):
        self.calls.append(("create_material_stream", name))
        return name

    def set_stream_temperature(self, *args):
        self.calls.append(("temperature", *args))

    def set_stream_pressure(self, *args):
        self.calls.append(("pressure", *args))

    def set_stream_flow(self, *args):
        self.calls.append(("flow", *args))

    def set_stream_composition(self, *args):
        self.calls.append(("composition", *args))

    def save_case(self, case_path):
        self.calls.append(("save_case", Path(case_path)))

    def create_reaction_set(self, name):
        self.calls.append(("create_reaction_set", name))
        return "reaction-set"

    create_equilibrium_reaction_set = create_reaction_set

    def add_conversion_reaction(self, *args):
        self.calls.append(("add_conversion_reaction", *args))

    def add_equilibrium_reaction(self, *args):
        self.calls.append(("add_equilibrium_reaction", *args))

    def create_conversion_reactor(self, name):
        self.calls.append(("create_conversion_reactor", name))
        return "reactor"

    def create_equilibrium_reactor(self, name):
        self.calls.append(("create_equilibrium_reactor", name))
        return "reactor"

    def connect_feed(self, *args):
        self.calls.append(("connect_feed", *args))

    def attach_reaction_set(self, *args):
        self.calls.append(("attach_reaction_set", *args))

    def set_adiabatic(self, *args):
        self.calls.append(("set_adiabatic", *args))

    def create_energy_stream(self, name):
        self.calls.append(("create_energy_stream", name))
        return name

    def connect_energy_stream(self, *args):
        self.calls.append(("connect_energy_stream", *args))

    def set_outlet_temperature(self, *args):
        self.calls.append(("set_outlet_temperature", *args))

    def set_outlet_pressure(self, *args):
        self.calls.append(("set_outlet_pressure", *args))

    def set_pressure_drop(self, *args):
        self.calls.append(("set_pressure_drop", *args))

    def solve(self):
        self.calls.append(("solve",))

    def read_case_result(self, built_case, spec):
        self.calls.append(("read_case_result", spec.reactor_type))
        return {
            "converged": True,
            "streams": {
                "Product": {
                    "temperature_k": 700.0,
                    "pressure_kpa": 1350.0,
                    "phase": "gas",
                    "composition_basis": "mole",
                    "mole_fractions": {"Methane": 1.0},
                    "molar_flows_kmol_h": {"Methane": 1.0},
                    "mass_flows_kg_h": {"Methane": 16.04},
                }
            },
            "reactor_duty_kw": 0.0,
            "warnings": [],
        }

    def close(self):
        self.calls.append(("close",))


def _session_factory(records):
    def factory(settings, *, application=None):
        session = RecordingRunSession(settings, application=application)
        records.append(session)
        return session

    return factory


def test_v15_adapter_runs_conversion_case_and_returns_real_source(tmp_path):
    records = []
    events = []
    spec = toluene_spec(
        assumptions=[Assumption(text="邻、间、对二甲苯按等选择性分配", confirmed=True)]
    )
    adapter = V15HysysAdapter(
        session_factory=_session_factory(records), application=object()
    )

    result = adapter.build_and_run(spec, tmp_path / "run-1", events.append)

    assert result.source == "hysys"
    assert result.converged is True
    assert len(result.case_paths) == 1
    assert Path(result.case_paths[0]).is_relative_to(tmp_path / "run-1")
    assert ("solve",) in records[0].calls
    assert records[0].calls[-1] == ("close",)
    assert RunState.SOLVING in [event.state for event in events]
    assert RunState.READING_RESULTS in [event.state for event in events]


def test_v15_adapter_preserves_build_failure_when_cleanup_also_fails(tmp_path):
    class BuildAndCleanupFailSession(RecordingRunSession):
        def create_case(self, case_path):
            raise RuntimeError("failed at pause_solver")

        def close(self):
            raise PermissionError("close access denied")

    def factory(settings, *, application=None):
        return BuildAndCleanupFailSession(settings, application=application)

    adapter = V15HysysAdapter(session_factory=factory, application=object())

    with pytest.raises(RuntimeError, match="failed at pause_solver"):
        adapter.build_and_run(
            toluene_spec(
                assumptions=[
                    Assumption(
                        text="邻、间、对二甲苯按等选择性分配",
                        confirmed=True,
                    )
                ]
            ),
            tmp_path / "failed-run",
            lambda event: None,
        )


def test_v15_adapter_runs_each_equilibrium_operating_case_separately(tmp_path):
    records = []
    adapter = V15HysysAdapter(
        session_factory=_session_factory(records), application=object()
    )

    result = adapter.build_and_run(
        steam_reforming_spec(), tmp_path / "run-2", lambda event: None
    )

    assert len(records) == 2
    assert len(result.case_paths) == 2
    assert len(set(result.case_paths)) == 2
    assert set(result.streams) == {"600C/Product", "710C/Product"}
    temperatures = [
        next(call[2] for call in record.calls if call[0] == "set_outlet_temperature")
        for record in records
    ]
    assert temperatures == [873.15, 983.15]
    assert all(record.calls[-1] == ("close",) for record in records)


def test_v15_adapter_keeps_non_ascii_equilibrium_case_paths_distinct(tmp_path):
    records = []
    spec = steam_reforming_spec()
    spec.operating_cases[0].name = "工况一"
    spec.operating_cases[1].name = "工况二"
    adapter = V15HysysAdapter(
        session_factory=_session_factory(records), application=object()
    )

    result = adapter.build_and_run(spec, tmp_path / "run-cn", lambda event: None)

    assert [Path(path).name for path in result.case_paths] == [
        "equilibrium-01-case.hsc",
        "equilibrium-02-case.hsc",
    ]
