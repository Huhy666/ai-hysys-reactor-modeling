import argparse
import contextlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.hysys.introspection import (  # noqa: E402
    collect_member_names,
    collect_member_signature,
    collect_type_library_matches,
    try_add_operation,
)
from app.hysys.template_case import open_case_moniker  # noqa: E402

OPERATION_TYPES = {
    "conversion": [
        "conversionreactorop",
        "conversionreactor",
        "Conversion Reactor",
    ],
    "equilibrium": [
        "equilibriumreactorop",
        "equilibriumreactor",
        "Equilibrium Reactor",
    ],
    "gibbs": ["gibbsreactorop", "gibbsreactor", "Gibbs Reactor"],
    "cstr": ["cstrop", "cstrreactorop", "cstr", "CSTR"],
    "pfr": ["pfrop", "pfrreactorop", "pfr", "PFR"],
}

OPERATION_TYPES["cstr"].extend(
    [
        "cstrreactor",
        "continuousstirredtankreactorop",
        "continuoustankreactorop",
        "tankreactorop",
        "Continuous Stirred Tank Reactor",
    ]
)
OPERATION_TYPES["pfr"].extend(
    [
        "pfrreactor",
        "plugflowreactorop",
        "plugflowreactor",
        "tubularreactorop",
        "Plug Flow Reactor",
    ]
)

REACTION_OBJECT_TYPES = {
    "reaction_set": ["reactionset", "rxnset", "ReactionSet", "Reaction Set"],
    "conversion_reaction": [
        "conversionrxn",
        "conversionreaction",
        "Conversion Reaction",
    ],
    "equilibrium_reaction": [
        "equilibriumrxn",
        "equilibriumreaction",
        "Equilibrium Reaction",
    ],
    "kinetic_reaction": ["kineticrxn", "kineticreaction", "Kinetic Reaction"],
}

TYPE_LIBRARY_KEYWORDS = (
    "reactor",
    "reaction",
    "rxn",
    "cstr",
    "pfr",
    "plugflow",
    "kinetic",
    "equilibrium",
    "conversion",
    "gibbs",
)

REACTION_CONTAINER_NAMES = (
    "ReactionPackage",
    "ReactionManager",
    "ReactionSets",
    "Reactions",
    "ReactionSet",
    "RxnPackage",
)

SIGNATURE_MEMBER_NAMES = ("Add", "Item", "Remove", "RemoveAll")


def _inspect_object(value: Any) -> dict[str, Any]:
    members = collect_member_names(value)
    return {
        "type_name": str(getattr(value, "TypeName", "")),
        "visible_type_name": str(getattr(value, "VisibleTypeName", "")),
        "members": members,
        "signatures": {
            name: collect_member_signature(value, name)
            for name in SIGNATURE_MEMBER_NAMES
            if name in members
        },
    }


def _inspect_named_members(value: Any) -> dict[str, Any]:
    result = {}
    for name in REACTION_CONTAINER_NAMES:
        try:
            member = getattr(value, name)
        except Exception as exc:
            result[name] = {"available": False, "error": f"{type(exc).__name__}: {exc}"}
            continue
        result[name] = {"available": True, **_inspect_object(member)}
    return result


def _inspect_reaction_graph(basis: Any, fluid_package: Any) -> dict[str, Any]:
    graph: dict[str, Any] = {}
    roots = (
        ("basis.ReactionPackageManager", basis, "ReactionPackageManager"),
        ("fluid_package.ReactionPackage", fluid_package, "ReactionPackage"),
    )
    for path, parent, member_name in roots:
        try:
            value = getattr(parent, member_name)
        except Exception as exc:
            graph[path] = {
                "available": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
            continue
        graph[path] = {"available": True, **_inspect_object(value)}
        for child_name in (
            "ReactionPackageManager",
            "ReactionSets",
            "Reactions",
            "ReactionTypes",
        ):
            child_path = f"{path}.{child_name}"
            try:
                child = getattr(value, child_name)
            except Exception as exc:
                graph[child_path] = {
                    "available": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                continue
            graph[child_path] = {"available": True, **_inspect_object(child)}
    return graph


def run_probe(settings: Settings, output_path: Path) -> dict[str, Any]:
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "hysys_version": None,
        "members": {},
        "signatures": {},
        "type_library": {},
        "reaction_containers": {},
        "reaction_graph": {},
        "reaction_object_types": {},
        "operation_types": {},
        "errors": [],
    }
    simulation_case = None
    application = None
    application_owned = False

    try:
        if settings.hysys_base_case_path is None:
            raise RuntimeError("HYSYS_BASE_CASE_PATH is not configured")
        seed = Path(settings.hysys_base_case_path).resolve()
        if not seed.is_file():
            raise FileNotFoundError(seed)

        temporary_directory = tempfile.TemporaryDirectory(prefix="hysys-reactor-probe-")
        working_case = Path(temporary_directory.name) / "reactor-probe.hsc"
        shutil.copy2(seed, working_case)
        simulation_case, application, application_owned = open_case_moniker(
            working_case,
            settings.hysys_progid,
        )
        application.Visible = settings.hysys_visible
        simulation_case.Visible = settings.hysys_visible
        report["hysys_version"] = str(application.Version)
        with contextlib.suppress(Exception):
            simulation_case.Solver.CanSolve = False

        basis = simulation_case.BasisManager
        flowsheet = simulation_case.Flowsheet
        operations = flowsheet.Operations
        report["members"] = {
            "case": collect_member_names(simulation_case),
            "basis": collect_member_names(basis),
            "flowsheet": collect_member_names(flowsheet),
            "operations": collect_member_names(operations),
        }
        report["signatures"]["flowsheet_operations"] = {
            name: collect_member_signature(operations, name)
            for name in SIGNATURE_MEMBER_NAMES
            if name in report["members"]["operations"]
        }
        report["type_library"] = collect_type_library_matches(
            operations,
            TYPE_LIBRARY_KEYWORDS,
        )
        report["reaction_containers"] = {
            "case": _inspect_named_members(simulation_case),
            "basis": _inspect_named_members(basis),
        }

        try:
            fluid_packages = basis.FluidPackages
            try:
                fluid_package = fluid_packages.Item(0)
            except Exception:
                fluid_package = fluid_packages.Item(1)
            report["members"]["fluid_package"] = collect_member_names(fluid_package)
            report["reaction_containers"]["fluid_package"] = _inspect_named_members(
                fluid_package
            )
            report["reaction_graph"] = _inspect_reaction_graph(basis, fluid_package)
            reaction_manager = basis.ReactionPackageManager
            reaction_collections = {
                "reaction_set": reaction_manager.ReactionSets,
                "conversion_reaction": reaction_manager.Reactions,
                "equilibrium_reaction": reaction_manager.Reactions,
                "kinetic_reaction": reaction_manager.Reactions,
            }
            for object_kind, candidates in REACTION_OBJECT_TYPES.items():
                report["reaction_object_types"][object_kind] = try_add_operation(
                    reaction_collections[object_kind],
                    candidates,
                    f"Probe-{object_kind}",
                )
        except Exception as exc:
            report["errors"].append(f"fluid_package: {type(exc).__name__}: {exc}")

        for reactor_type, candidates in OPERATION_TYPES.items():
            report["operation_types"][reactor_type] = try_add_operation(
                operations,
                candidates,
                f"Probe-{reactor_type}",
            )
    except Exception as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        if simulation_case is not None:
            with contextlib.suppress(Exception):
                simulation_case.Close(False)
        if application_owned and application is not None:
            with contextlib.suppress(Exception):
                application.Quit()
        if "temporary_directory" in locals():
            temporary_directory.cleanup()

    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect HYSYS V15 reactor and reaction COM members on a seed copy"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("runs/reactor-api-probe.json"),
    )
    args = parser.parse_args()
    report = run_probe(Settings(), args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
