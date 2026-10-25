import argparse
import contextlib
import json
import shutil
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.hysys.introspection import (  # noqa: E402
    collect_member_names,
    collect_member_signature,
    try_create_named_object,
)
from app.hysys.template_case import open_case_moniker  # noqa: E402

OPERATION_TYPES = {
    "conversion": ["conversionreactorop"],
    "equilibrium": ["equilibriumreactorop"],
    "gibbs": ["gibbsreactorop"],
    "cstr": [
        "kineticreactorop",
        "kineticreactor",
        "cstrreactorop",
        "cstrreactor",
    ],
    "pfr": [
        "pfreactorop",
        "pfreactor",
        "pfrreactorop",
        "pfrreactor",
        "plugflowreactorop",
    ],
}

REACTION_TYPES = {
    "conversion": "conversionrxn",
    "equilibrium": "equilibriumrxn",
    "kinetic": "kineticrxn",
}

SIGNATURE_MEMBERS = (
    "Add",
    "AssociateFluidPackage",
    "Item",
    "Remove",
    "SetValue",
    "SetValues",
)

REACTION_CHILDREN = (
    "BaseComponent",
    "Conversion",
    "ConversionCoefficients",
    "Reactants",
    "ReactantName",
    "ReactantStoichCoef",
    "ForwardActivationEnergy",
    "ForwardFrequencyFactor",
)

REACTION_SET_CHILDREN = (
    "ActiveReactions",
    "InactiveReactions",
    "Operations",
)

REACTOR_CHILDREN = (
    "AttachedFeeds",
    "AttachedProducts",
    "EnergyStream",
    "EnergyStreamVar",
    "Feeds",
    "LiquidProduct",
    "LiquidProductVar",
    "Product",
    "ProductVar",
    "ReactionSet",
    "VapourProduct",
    "VapourProductVar",
)


def _inspect_object(value: Any) -> dict[str, Any]:
    members = collect_member_names(value)
    return {
        "python_type": type(value).__name__,
        "name": str(getattr(value, "name", "")),
        "type_name": str(getattr(value, "TypeName", "")),
        "visible_type_name": str(getattr(value, "VisibleTypeName", "")),
        "members": members,
        "signatures": {
            name: collect_member_signature(value, name)
            for name in SIGNATURE_MEMBERS
            if name in members
        },
    }


def _inspect_children(value: Any, child_names: tuple[str, ...]) -> dict[str, Any]:
    report = {}
    for child_name in child_names:
        try:
            child = getattr(value, child_name)
        except Exception as exc:
            report[child_name] = {
                "available": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
            continue
        if child is None or isinstance(child, (bool, float, int, str)):
            report[child_name] = {
                "available": True,
                "value": child,
                "python_type": type(child).__name__,
            }
            continue
        try:
            inspected = _inspect_object(child)
        except Exception as exc:
            inspected = {
                "python_type": type(child).__name__,
                "repr": repr(child),
                "inspection_error": f"{type(exc).__name__}: {exc}",
            }
        report[child_name] = {"available": True, **inspected}
    return report


def _attempt(action: Callable[[], Any]) -> dict[str, Any]:
    try:
        result = action()
    except Exception as exc:
        return {
            "success": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "success": True,
        "result_type": type(result).__name__,
        "result": (
            result
            if result is None or isinstance(result, (bool, float, int, str))
            else repr(result)
        ),
    }


def _create_known(collection: Any, name: str, type_name: str) -> tuple[Any | None, dict[str, Any]]:
    try:
        created = collection.Add(name, type_name)
    except Exception as exc:
        return None, {
            "success": False,
            "name": name,
            "type_name": type_name,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return created, {
        "success": True,
        "name": name,
        "type_name": type_name,
        "identity": _inspect_object(created),
    }


def run_probe(settings: Settings, output_path: Path) -> dict[str, Any]:
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "hysys_version": None,
        "operations": {},
        "reaction_set": {},
        "reactions": {},
        "connections": {},
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

        temporary_directory = tempfile.TemporaryDirectory(prefix="hysys-reactor-detail-")
        working_case = Path(temporary_directory.name) / "reactor-detail.hsc"
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
        try:
            fluid_package = basis.FluidPackages.Item(0)
        except Exception:
            fluid_package = basis.FluidPackages.Item(1)

        created_operations = {}
        for reactor_kind, candidates in OPERATION_TYPES.items():
            created, creation_report = try_create_named_object(
                operations,
                candidates,
                f"Probe-{reactor_kind}",
            )
            report["operations"][reactor_kind] = creation_report
            if created is not None:
                created_operations[reactor_kind] = created
                report["operations"][reactor_kind]["children"] = _inspect_children(
                    created,
                    REACTOR_CHILDREN,
                )

        manager = basis.ReactionPackageManager
        reaction_set, reaction_set_report = _create_known(
            manager.ReactionSets,
            "Probe-Reaction-Set",
            "reactionset",
        )
        report["reaction_set"] = reaction_set_report
        if reaction_set is not None:
            report["reaction_set"]["children"] = _inspect_children(
                reaction_set,
                REACTION_SET_CHILDREN,
            )
            report["reaction_set"]["associate_fluid_package"] = _attempt(
                lambda: reaction_set.AssociateFluidPackage(fluid_package)
            )

        created_reactions = {}
        for reaction_kind, type_name in REACTION_TYPES.items():
            reaction, reaction_report = _create_known(
                manager.Reactions,
                f"Probe-{reaction_kind}-reaction",
                type_name,
            )
            report["reactions"][reaction_kind] = reaction_report
            if reaction is not None:
                created_reactions[reaction_kind] = reaction
                report["reactions"][reaction_kind]["children"] = _inspect_children(
                    reaction,
                    REACTION_CHILDREN,
                )

        if reaction_set is not None and "conversion" in created_reactions:
            conversion_reaction = created_reactions["conversion"]
            active_reactions = reaction_set.ActiveReactions
            report["reaction_set"]["activate_by_object"] = _attempt(
                lambda: active_reactions.Add(conversion_reaction)
            )
            report["reaction_set"]["activate_by_name"] = _attempt(
                lambda: active_reactions.Add(conversion_reaction.name)
            )

        feed = flowsheet.MaterialStreams.Add("Probe-Feed")
        vapour = flowsheet.MaterialStreams.Add("Probe-Vapour")
        liquid = flowsheet.MaterialStreams.Add("Probe-Liquid")
        product = flowsheet.MaterialStreams.Add("Probe-Product")
        energy = flowsheet.EnergyStreams.Add("Probe-Energy")

        for reactor_kind, reactor in created_operations.items():
            connection_report = {
                "feed_add_object": _attempt(lambda reactor=reactor: reactor.Feeds.Add(feed)),
                "reaction_set_object": (
                    _attempt(lambda reactor=reactor: setattr(reactor, "ReactionSet", reaction_set))
                    if reaction_set is not None
                    else {"success": False, "error": "reaction set unavailable"}
                ),
                "energy_object": _attempt(
                    lambda reactor=reactor: setattr(reactor, "EnergyStream", energy)
                ),
            }
            if reactor_kind == "pfr":
                connection_report["product_object"] = _attempt(
                    lambda reactor=reactor: setattr(reactor, "Product", product)
                )
            else:
                connection_report["vapour_product_object"] = _attempt(
                    lambda reactor=reactor: setattr(reactor, "VapourProduct", vapour)
                )
                connection_report["liquid_product_object"] = _attempt(
                    lambda reactor=reactor: setattr(reactor, "LiquidProduct", liquid)
                )
            report["connections"][reactor_kind] = connection_report
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
        description="Inspect detailed HYSYS V15 reactor wiring on a disposable seed copy"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("runs/reactor-detail-probe.json"),
    )
    args = parser.parse_args()
    report = run_probe(Settings(), args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
