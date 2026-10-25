from pathlib import Path

from app.config import Settings
from scripts import probe_hysys


class FakeTemperature:
    def __init__(self):
        self.kelvin = None

    def SetValue(self, value, unit):
        assert unit == "K"
        self.kelvin = value

    def GetValue(self, unit):
        assert unit == "K"
        return self.kelvin


class FakeStream:
    def __init__(self):
        self.Temperature = FakeTemperature()


class FakeMaterialStreams:
    def __init__(self):
        self.stream = None

    def Item(self, name):
        raise RuntimeError(name)

    def Add(self, name):
        assert name == "ProbeFeed"
        self.stream = FakeStream()
        return self.stream


class FakeCase:
    def __init__(self, application):
        self.Application = application
        self.Visible = False
        self.Flowsheet = type(
            "Flowsheet", (), {"MaterialStreams": FakeMaterialStreams()}
        )()
        self.Solver = type("Solver", (), {"CanSolve": True})()
        component_lists = type("ComponentLists", (), {"Count": 1})()
        fluid_package = type(
            "FluidPackage", (), {"PropertyPackageName": "Peng-Robinson"}
        )()
        fluid_packages = type(
            "FluidPackages",
            (),
            {"Count": 1, "Item": lambda self, index: fluid_package},
        )()
        self.BasisManager = type(
            "BasisManager",
            (),
            {"ComponentLists": component_lists, "FluidPackages": fluid_packages},
        )()
        self.save_calls = 0
        self.close_calls = 0

    def Activate(self):
        return None

    def Save(self):
        self.save_calls += 1

    def Close(self, save_changes):
        assert save_changes is False
        self.close_calls += 1


class FakeApplication:
    Version = "Aspen HYSYS Version 15 (41.0)"

    def __init__(self):
        self.Visible = False
        self.quit_calls = 0

    def Quit(self):
        self.quit_calls += 1


def test_probe_uses_seed_copy_and_preserves_unowned_application(tmp_path, monkeypatch):
    seed = tmp_path / "seed" / "base-case.hsc"
    seed.parent.mkdir()
    seed.write_bytes(b"verified seed")
    application = FakeApplication()
    simulation_case = FakeCase(application)
    opened_paths: list[Path] = []
    opened_bytes: list[bytes] = []

    def fake_open(path, _progid):
        opened_paths.append(Path(path))
        opened_bytes.append(Path(path).read_bytes())
        return simulation_case, application, False

    monkeypatch.setattr(probe_hysys, "open_case_moniker", fake_open)
    report = probe_hysys.run_probe(
        Settings(_env_file=None, hysys_base_case_path=seed),
        tmp_path / "out" / "probe-result.json",
    )

    assert report.all_required is True
    assert report.capabilities.blank_case is False
    assert report.capabilities.seed_case is True
    assert opened_paths and opened_paths[0] != seed
    assert opened_bytes == [seed.read_bytes()]
    assert simulation_case.save_calls == 1
    assert simulation_case.close_calls == 1
    assert application.quit_calls == 0
    assert (tmp_path / "out" / "probe-case.hsc").read_bytes() == seed.read_bytes()
