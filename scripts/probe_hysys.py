import argparse
import contextlib
import json
import platform
import shutil
import sys
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict, computed_field

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.hysys.interface import HysysCapabilities  # noqa: E402
from app.hysys.template_case import open_case_moniker  # noqa: E402


class ProbeReport(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    capabilities: HysysCapabilities
    output_path: Path

    @computed_field
    @property
    def all_required(self) -> bool:
        return self.capabilities.all_required


def _read_version(application) -> str:
    for name in ("Version", "ApplicationVersion"):
        value = getattr(application, name, None)
        if value:
            return str(value)
    raise AttributeError("HYSYS version property was not found")


def _collection_item(collection, index: int):
    try:
        return collection.Item(index)
    except Exception:
        return collection.Item(index + 1)


def _verify_seed_case(simulation_case) -> bool:
    basis = simulation_case.BasisManager
    if int(basis.ComponentLists.Count) < 1 or int(basis.FluidPackages.Count) < 1:
        return False
    fluid_package = _collection_item(basis.FluidPackages, 0)
    return bool(str(fluid_package.PropertyPackageName))


def run_probe(
    settings: Settings,
    output_path: Path,
    *,
    allow_existing_blank_session: bool = False,
) -> ProbeReport:
    del allow_existing_blank_session

    errors: list[str] = []
    flags = {
        "dispatch": False,
        "version_read": False,
        "blank_case": False,
        "seed_case": False,
        "stream_round_trip": False,
        "case_save": False,
    }
    version = None
    application = None
    application_owned = False
    simulation_case = None
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    case_path = output_path.with_name("probe-case.hsc")
    base_case_path = settings.hysys_base_case_path

    try:
        if base_case_path is None:
            raise RuntimeError("HYSYS_BASE_CASE_PATH is not configured")
        base_case_path = Path(base_case_path).resolve()
        if not base_case_path.is_file():
            raise FileNotFoundError(base_case_path)

        temporary_directory = tempfile.TemporaryDirectory(prefix="hysys-probe-")
        working_case_path = Path(temporary_directory.name) / "probe-case.hsc"
        shutil.copy2(base_case_path, working_case_path)
        simulation_case, application, application_owned = open_case_moniker(
            working_case_path, settings.hysys_progid
        )
        flags["dispatch"] = True
        application.Visible = settings.hysys_visible
        version = _read_version(application)
        flags["version_read"] = True
        flags["seed_case"] = _verify_seed_case(simulation_case)
        simulation_case.Visible = settings.hysys_visible
        activate = getattr(simulation_case, "Activate", None)
        if callable(activate):
            activate()
        with contextlib.suppress(Exception):
            simulation_case.Solver.CanSolve = False
        try:
            stream = simulation_case.Flowsheet.MaterialStreams.Item("ProbeFeed")
        except Exception:
            stream = simulation_case.Flowsheet.MaterialStreams.Add("ProbeFeed")
        stream.Temperature.SetValue(300.0, "K")
        round_trip = float(stream.Temperature.GetValue("K"))
        flags["stream_round_trip"] = abs(round_trip - 300.0) < 1e-6
        simulation_case.Save()
        simulation_case.Close(False)
        simulation_case = None
        shutil.copy2(working_case_path, case_path)
        flags["case_save"] = case_path.is_file() and case_path.stat().st_size > 0
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    finally:
        if simulation_case is not None:
            try:
                simulation_case.Close(False)
            except Exception as exc:
                errors.append(f"case_close: {type(exc).__name__}: {exc}")
        if application_owned and application is not None:
            try:
                application.Quit()
            except Exception as exc:
                errors.append(f"app_close: {type(exc).__name__}: {exc}")
        if "temporary_directory" in locals():
            temporary_directory.cleanup()

    capabilities = HysysCapabilities(
        python_architecture=platform.architecture()[0],
        progid=settings.hysys_progid,
        architecture_compatible=platform.architecture()[0] == "64bit",
        progid_configured=bool(settings.hysys_progid),
        hysys_version=version,
        errors=errors,
        **flags,
    )
    report = ProbeReport(capabilities=capabilities, output_path=output_path)
    output_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe a copied HYSYS V15 seed case through its file moniker"
    )
    parser.add_argument("--output", type=Path, default=Path("runs/probe-result.json"))
    parser.add_argument("--allow-existing-blank-session", action="store_true")
    args = parser.parse_args()
    report = run_probe(
        Settings(),
        args.output,
        allow_existing_blank_session=args.allow_existing_blank_session,
    )
    print(report.capabilities.model_dump_json(indent=2))
    return 0 if report.all_required else 1


if __name__ == "__main__":
    raise SystemExit(main())
