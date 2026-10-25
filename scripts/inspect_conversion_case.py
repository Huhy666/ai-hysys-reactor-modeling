"""Read a disposable copy of a saved failed toluene case without rebuilding it."""

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.domain.models import SimulationSpec  # noqa: E402
from app.hysys.template_case import open_case_moniker  # noqa: E402
from app.hysys.v15_session import V15CaseSession  # noqa: E402


def find_failed_run(root: Path) -> Path:
    candidates = []
    for path in root.glob("*/run.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if (record.get("state") == "failed"
                    and "specified conversion not reached" in (record.get("error") or "")
                    and (path.parent / "conversion.hsc").is_file()):
                candidates.append((record["updated_at"], path.parent))
        except (OSError, ValueError, KeyError):
            continue
    if not candidates:
        raise FileNotFoundError("No saved failed conversion case under the configured runs path")
    return max(candidates)[1]


def inspect(run_dir: Path, settings: Settings) -> Path:
    record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    spec = SimulationSpec.model_validate(record["spec"])
    if spec.known_conversion is None:
        raise ValueError("Inspection requires the recorded total toluene conversion")
    output = run_dir / "case-readback.json"
    session = V15CaseSession(settings)
    with tempfile.TemporaryDirectory(prefix="hysys-readback-") as temporary:
        copy = Path(temporary) / "conversion-readback.hsc"
        shutil.copy2(run_dir / "conversion.hsc", copy)
        try:
            case, application, owned = open_case_moniker(copy, settings.hysys_progid)
            session.simulation_case = case
            session.application = application
            session._application_owned = owned
            # Pause only the disposable copy. Do not change the recorded original.
            case.Solver.CanSolve = False
            session._basis = case.BasisManager
            session._flowsheet = case.Flowsheet
            session._component_list = session._basis.ComponentLists.Item("AI HYSYS Components")
            session._component_names = [c.hysys_name or c.user_name for c in spec.components]
            reactor = session._flowsheet.Operations.Item("Conversion Reactor")
            session._reactor = reactor
            session._connected_feeds = [session._flowsheet.MaterialStreams.Item(feed.name)
                                        for feed in spec.feeds]
            session._output_streams = {
                str(reactor.VapourProduct.name): (reactor.VapourProduct, "gas"),
                str(reactor.LiquidProduct.name): (reactor.LiquidProduct, "liquid"),
            }
            session._conversion_targets = {"Toluene": spec.known_conversion}
            error = ""
            try:
                session._solution_snapshot()
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            report = session.write_solver_diagnostics(output, error)
            report["run_id"] = record["id"]
            report["source"] = "saved_hysys_case_copy"
            report["original_case_modified"] = False
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report.get("conversion_checks", {}), ensure_ascii=False, indent=2))
            print("Reactor controls:", flush=True)
            print(json.dumps(report.get("reactor_controls", {}), ensure_ascii=False, indent=2))
        finally:
            session.close()
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args()
    os.chdir(ROOT)
    settings = Settings()
    try:
        run_dir = args.run_dir or find_failed_run(settings.hysys_artifact_dir)
        print(f"Inspecting saved case: {run_dir}", flush=True)
        output = inspect(run_dir, settings)
        print(f"Readback complete. Send this file: {output}", flush=True)
        return 0
    except Exception as exc:
        print(f"Inspection failed: {type(exc).__name__}: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
