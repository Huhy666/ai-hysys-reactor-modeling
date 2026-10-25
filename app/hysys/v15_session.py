from __future__ import annotations

import contextlib
import json
import math
import re
import shutil
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from app.config import Settings
from app.domain.models import SimulationSpec
from app.domain.result_validation import validate_stream_balance
from app.hysys.case_builder import BuiltCase
from app.hysys.component_mapping import resolve_component
from app.hysys.introspection import collect_reactor_control_properties
from app.hysys.template_case import open_case_moniker

V15_COMPONENT_IDENTIFIERS = {
    "Water": "H2O",
    "Carbon Monoxide": "CO",
    "Carbon Dioxide": "CO2",
}


def _first(collection: Any) -> Any:
    try:
        return collection.Item(0)
    except Exception:
        return collection.Item(1)


def _normalized_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def _known(variable: Any) -> bool:
    try:
        return bool(variable.IsKnown)
    except Exception:
        try:
            return bool(variable.IsKnown())
        except Exception:
            return True


def _put_typed_boolean(value: Any, member: str, enabled: bool) -> None:
    """Explicit VARIANT_BOOL property put, avoiding late-bound argument inference."""
    import pythoncom

    dispatch = value._oleobj_
    dispid = dispatch.GetIDsOfNames(member)
    if isinstance(dispid, (tuple, list)):
        dispid = dispid[0]
    dispatch.InvokeTypes(
        dispid, 0, pythoncom.DISPATCH_PROPERTYPUT, (pythoncom.VT_EMPTY, 0),
        ((pythoncom.VT_BOOL, 0),), bool(enabled),
    )


class V15CaseSession:
    """One disposable V15 case opened from the verified seed case."""

    def __init__(
        self,
        settings: Settings,
        *,
        application: Any | None = None,
        opener: Callable[[Path, str], tuple[Any, Any, bool]] = open_case_moniker,
    ) -> None:
        self.settings = settings
        self.application = application
        self._opener = opener
        self.simulation_case: Any | None = None
        self.version: str | None = None
        self._basis: Any | None = None
        self._flowsheet: Any | None = None
        self._component_list: Any | None = None
        self._fluid_package: Any | None = None
        self._component_names: list[str] = []
        self._hysys_component_names: dict[str, str] = {}
        self._output_streams: dict[str, tuple[Any, str]] = {}
        self._connected_feeds: list[Any] = []
        self._conversion_targets: dict[str, float] = {}
        self._reactor: Any | None = None
        self._application_owned = False
        self._basis_change_active = False
        self._diagnostic_path: Path | None = None
        self._conversion_checks: dict[str, dict[str, Any]] = {}
        self._separator_control: dict[str, Any] = {}
        self._operator_attention_requested = False

    def _require_case(self) -> None:
        if self.simulation_case is None:
            raise RuntimeError("HYSYS case has not been created")

    @staticmethod
    def _initialize_step(checkpoint: str, operation: Callable[[], Any]) -> Any:
        try:
            return operation()
        except Exception as exc:
            raise RuntimeError(
                f"initializing copied HYSYS case failed at {checkpoint}"
            ) from exc

    @staticmethod
    def _com_step(checkpoint: str, operation: Callable[[], Any]) -> Any:
        try:
            return operation()
        except Exception as exc:
            raise RuntimeError(
                f"HYSYS COM operation failed at {checkpoint}: {type(exc).__name__}: {exc}"
            ) from exc

    def create_case(self, case_path: Path) -> object:
        if self.simulation_case is not None:
            raise RuntimeError("this V15 session already owns a case")
        if self.settings.hysys_base_case_path is None:
            raise RuntimeError("HYSYS_BASE_CASE_PATH is not configured")
        seed = Path(self.settings.hysys_base_case_path).resolve()
        if not seed.is_file():
            raise FileNotFoundError(seed)
        target = Path(case_path).resolve()
        self._case_filename = target.name
        self._diagnostic_path = target.with_name("solver-diagnostics.json")
        if target.suffix.casefold() != ".hsc":
            raise ValueError("case path must use the .hsc extension")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(seed, target)

        try:
            simulation_case, case_application, application_owned = self._opener(
                target, self.settings.hysys_progid
            )
        except Exception as exc:
            raise RuntimeError(
                "opening copied HYSYS seed case through its file moniker failed"
            ) from exc
        self.simulation_case = simulation_case
        self.application = case_application
        self._application_owned = application_owned
        self.version = str(
            self._initialize_step("read_version", lambda: case_application.Version)
        )
        self._initialize_step(
            "set_application_visible",
            lambda: setattr(case_application, "Visible", self.settings.hysys_visible),
        )
        self._initialize_step(
            "set_case_visible",
            lambda: setattr(simulation_case, "Visible", self.settings.hysys_visible),
        )
        activate = getattr(simulation_case, "Activate", None)
        if callable(activate):
            self._initialize_step("activate_case", activate)
        self._initialize_step(
            "pause_solver",
            lambda: setattr(simulation_case.Solver, "CanSolve", False),
        )
        self._basis = self._initialize_step(
            "get_basis_manager", lambda: simulation_case.BasisManager
        )
        self._flowsheet = self._initialize_step(
            "get_flowsheet", lambda: simulation_case.Flowsheet
        )
        self._fluid_package = self._initialize_step(
            "get_fluid_package", lambda: _first(self._basis.FluidPackages)
        )
        changing_basis = bool(
            self._initialize_step(
                "read_basis_change_state",
                lambda: self._basis.IsChangingBasis,
            )
        )
        if not changing_basis:
            self._initialize_step(
                "start_basis_change",
                self._basis.StartBasisChange,
            )
        self._basis_change_active = True
        self._component_list = self._initialize_step(
            "create_component_list",
            lambda: self._basis.ComponentLists.Add("AI HYSYS Components"),
        )
        return simulation_case

    def add_component(self, name: str) -> None:
        self._require_case()
        if name in self._component_names:
            return
        hysys_name = V15_COMPONENT_IDENTIFIERS.get(name, name)
        components = self._com_step(
            "get_component_collection",
            lambda: self._component_list.Components,
        )
        try:
            existing = components.Item(hysys_name)
        except Exception:
            existing = None
        if existing is None:
            self._com_step(
                f"add_component:{name}",
                lambda: components.Add(hysys_name),
            )
        self._component_names.append(name)
        self._hysys_component_names[name] = hysys_name

    def set_fluid_package(self, name: str) -> None:
        self._require_case()
        actual = self._com_step(
            "read_fluid_package",
            lambda: getattr(self._fluid_package, "PropertyPackageName", ""),
        )
        if _normalized_name(name) != _normalized_name(actual):
            raise ValueError(
                f"seed fluid package is {actual!s}, requested package is {name!s}"
            )
        self._com_step(
            "assign_component_list_to_fluid_package",
            lambda: setattr(self._fluid_package, "ComponentList", self._component_list),
        )
        self._end_basis_change()

    def _end_basis_change(self) -> None:
        if not self._basis_change_active:
            return
        timeout = min(float(self.settings.hysys_run_timeout_seconds), 30.0)
        deadline = time.monotonic() + max(timeout, 1.0)
        while time.monotonic() < deadline:
            ready = bool(
                self._com_step(
                    "check_basis_change_ready",
                    lambda: self._basis.CanEndBasisChange,
                )
            )
            if ready:
                break
            try:
                import pythoncom

                pythoncom.PumpWaitingMessages()
            except ImportError:
                pass
            time.sleep(0.1)
        else:
            raise TimeoutError("HYSYS basis change did not become ready")
        self._com_step("end_basis_change", self._basis.EndBasisChange)
        self._basis_change_active = False

    def create_material_stream(self, name: str) -> object:
        self._require_case()
        return self._com_step(
            f"create_material_stream:{name}",
            lambda: self._flowsheet.MaterialStreams.Add(name),
        )

    def set_stream_temperature(
        self, stream: object, value: float, unit: str
    ) -> None:
        self._com_step(
            "set_stream_temperature",
            lambda: stream.Temperature.SetValue(value, unit),
        )

    def set_stream_pressure(self, stream: object, value: float, unit: str) -> None:
        self._com_step(
            "set_stream_pressure",
            lambda: stream.Pressure.SetValue(value, unit),
        )

    def set_stream_flow(self, stream: object, value: float, unit: str) -> None:
        def operation() -> None:
            variable = stream.MolarFlow if unit == "kmol/h" else stream.MassFlow
            # V15 accepts kgmole/h, not kmol/h; these have identical magnitude.
            hysys_unit = "kgmole/h" if unit == "kmol/h" else unit
            variable.SetValue(value, hysys_unit)

        self._com_step(f"set_stream_flow:{unit}", operation)

    def set_stream_composition(
        self, stream: object, composition: dict[str, float]
    ) -> None:
        missing = set(composition) - set(self._component_names)
        if missing:
            raise ValueError(f"composition contains components not in case: {missing}")
        values = tuple(composition.get(name, 0.0) for name in self._component_names)
        self._com_step(
            "set_stream_composition",
            lambda: stream.ComponentMolarFraction.SetValues(values, ""),
        )

    def save_case(self, case_path: Path) -> None:
        self._require_case()
        self._com_step("save_case", self.simulation_case.Save)
        if not Path(case_path).resolve().is_file():
            raise RuntimeError("HYSYS did not save the case file")

    def _reaction_manager(self) -> Any:
        self._require_case()
        return self._com_step(
            "get_reaction_manager",
            lambda: self._basis.ReactionPackageManager,
        )

    def create_reaction_set(self, name: str) -> object:
        reaction_set = self._com_step(
            f"create_reaction_set:{name}",
            lambda: self._reaction_manager().ReactionSets.Add(name, "reactionset"),
        )
        self._com_step(
            f"associate_fluid_package:{name}",
            lambda: reaction_set.AssociateFluidPackage(self._fluid_package),
        )
        return reaction_set

    def create_equilibrium_reaction_set(self, name: str) -> object:
        return self.create_reaction_set(name)

    def _add_reaction(
        self,
        reaction_set: object,
        name: str,
        type_name: str,
        stoichiometry: Mapping[str, float],
    ) -> Any:
        reaction = self._com_step(
            f"create_reaction:{name}:{type_name}",
            lambda: self._reaction_manager().Reactions.Add(name, type_name),
        )
        resolved_stoichiometry: dict[str, float] = {}
        for component, coefficient in stoichiometry.items():
            match = resolve_component(component)
            if match.hysys_name is None or match.requires_confirmation:
                raise ValueError(f"reaction component requires confirmation: {component}")
            resolved_stoichiometry[match.hysys_name] = (
                resolved_stoichiometry.get(match.hysys_name, 0.0) + coefficient
            )
        missing = set(resolved_stoichiometry) - set(self._component_names)
        if missing:
            raise ValueError(f"reaction contains components not in case: {missing}")
        component_names = tuple(resolved_stoichiometry)
        hysys_component_names = tuple(
            self._hysys_component_names[item] for item in component_names
        )
        for component in hysys_component_names:
            self._com_step(
                f"add_reaction_component:{name}:{component}",
                lambda component=component: reaction.Reactants.Add(component),
            )

        def read_component_order() -> tuple[str, ...]:
            count = int(reaction.Reactants.Count)
            names = tuple(reaction.ReactantName.Values)
            # V15 returns an extra empty editable row after the real reactants.
            actual = names[:count]
            if (
                count != len(hysys_component_names)
                or len(actual) != count
                or set(actual) != set(hysys_component_names)
                or any(names[count:])
            ):
                raise ValueError(f"reaction component readback mismatch: {names!r}")
            return actual

        actual_names = self._com_step(
            f"read_reaction_components:{name}", read_component_order
        )
        coefficients_by_name = {
            self._hysys_component_names[item]: float(resolved_stoichiometry[item])
            for item in component_names
        }
        coefficients = tuple(coefficients_by_name[item] for item in actual_names)
        self._com_step(
            f"set_reaction_stoichiometry:{name}",
            lambda: reaction.ReactantStoichCoef.SetValues(coefficients, ""),
        )
        self._com_step(
            f"activate_reaction:{name}",
            lambda: reaction_set.ActiveReactions.Add(reaction),
        )
        return reaction

    def add_conversion_reaction(
        self,
        reaction_set: object,
        name: str,
        stoichiometry: dict[str, float],
        base_component: str,
        conversion: float,
    ) -> None:
        reaction = self._add_reaction(
            reaction_set, name, "conversionrxn", stoichiometry
        )
        base_match = resolve_component(base_component)
        if base_match.hysys_name is None or base_match.requires_confirmation:
            raise ValueError(
                f"reaction base component requires confirmation: {base_component}"
            )
        base_name = self._hysys_component_names[base_match.hysys_name]
        base_object = self._com_step(
            f"get_conversion_base_component:{name}",
            lambda: self._component_list.Components.Item(base_name),
        )
        self._com_step(
            f"set_conversion_base_component:{name}",
            lambda: setattr(reaction, "BaseComponent", base_object),
        )

        def verify_base_component() -> None:
            actual = str(reaction.BaseComponent.name)
            if actual != base_name:
                raise ValueError(f"base component readback mismatch: {actual!r}")

        self._com_step(
            f"verify_conversion_base_component:{name}", verify_base_component
        )
        self._com_step(
            f"set_conversion_coefficients:{name}",
            lambda: reaction.ConversionCoefficients.SetValues(
                (float(conversion) * 100.0, 0.0, 0.0), ""
            ),
        )
        # Supported builder uses parallel reactions based on original feed.
        canonical = base_match.hysys_name
        self._conversion_targets[canonical] = (
            self._conversion_targets.get(canonical, 0.0) + float(conversion)
        )

    def add_equilibrium_reaction(
        self,
        reaction_set: object,
        name: str,
        stoichiometry: dict[str, float],
    ) -> None:
        self._add_reaction(reaction_set, name, "equilibriumrxn", stoichiometry)

    def _create_products(self, reactor: Any, name: str) -> None:
        vapour = self._com_step(
            f"create_vapour_product:{name}",
            lambda: self._flowsheet.MaterialStreams.Add(f"{name}-Vapour"),
        )
        liquid = self._com_step(
            f"create_liquid_product:{name}",
            lambda: self._flowsheet.MaterialStreams.Add(f"{name}-Liquid"),
        )
        self._com_step(
            f"connect_vapour_product:{name}",
            lambda: setattr(reactor, "VapourProduct", vapour),
        )
        self._com_step(
            f"connect_liquid_product:{name}",
            lambda: setattr(reactor, "LiquidProduct", liquid),
        )
        self._output_streams[vapour.name] = (vapour, "gas")
        self._output_streams[liquid.name] = (liquid, "liquid")

    def _create_reactor(self, name: str, type_name: str) -> Any:
        reactor = self._com_step(
            f"create_reactor:{name}:{type_name}",
            lambda: self._flowsheet.Operations.Add(name, type_name),
        )
        self._create_products(reactor, name)
        self._reactor = reactor
        return reactor

    def create_conversion_reactor(self, name: str) -> object:
        return self._create_reactor(name, "conversionreactorop")

    def create_equilibrium_reactor(self, name: str) -> object:
        return self._create_reactor(name, "equilibriumreactorop")

    def connect_feed(self, reactor: object, feed_name: str) -> None:
        feed = self._com_step(
            f"find_feed:{feed_name}",
            lambda: self._flowsheet.MaterialStreams.Item(feed_name),
        )
        self._com_step(
            f"connect_feed:{feed_name}",
            lambda: reactor.Feeds.Add(feed),
        )
        self._connected_feeds.append(feed)

    def attach_reaction_set(self, reactor: object, reaction_set: object) -> None:
        self._com_step(
            "attach_reaction_set",
            lambda: setattr(reactor, "ReactionSet", reaction_set),
        )
        def verify_controls():
            for member in ("ActAsSeparatorWhenCannotSolve", "IsIgnored"):
                before = getattr(reactor, member)
                setattr(reactor, member, False)
                after = getattr(reactor, member)
                if bool(after) and getattr(reactor, "_oleobj_", None) is not None:
                    _put_typed_boolean(reactor, member, False)
                    after = getattr(reactor, member)
                if bool(after) and member == "IsIgnored":
                    raise ValueError(
                        f"{member} did not accept False; before={before!r}, after={after!r}"
                    )
                if member == "ActAsSeparatorWhenCannotSolve":
                    self._separator_control = {
                        "method": "com_before_feed_ready", "before": before, "after": after,
                        "deferred_until_feed_ready": bool(after),
                    }

        try:
            self._com_step("verify_reactor_calculation_controls", verify_controls)
        except Exception:
            if self._diagnostic_path is not None:
                # Preserve the underlying transport/control problem before case cleanup.
                with contextlib.suppress(Exception):
                    self.write_solver_diagnostics(
                        self._diagnostic_path, "reactor calculation control readback failed",
                    )
            raise

    def set_adiabatic(self, reactor: object, enabled: bool) -> None:
        if not enabled:
            raise ValueError("non-adiabatic conversion is not implemented")
        energy_stream = self.create_energy_stream(f"Q-{reactor.name}")
        self.connect_energy_stream(reactor, energy_stream)
        self._com_step(
            "set_adiabatic_heat_flow",
            lambda: reactor.HeatFlow.SetValue(0.0, "kW"),
        )
        self.set_pressure_drop(reactor, 0.0, "kPa")

    def create_energy_stream(self, name: str) -> object:
        return self._com_step(
            f"create_energy_stream:{name}",
            lambda: self._flowsheet.EnergyStreams.Add(name),
        )

    def connect_energy_stream(self, reactor: object, energy_stream: object) -> None:
        self._com_step(
            "connect_energy_stream",
            lambda: setattr(reactor, "EnergyStream", energy_stream),
        )

    def set_outlet_temperature(
        self, reactor: object, value: float, unit: str
    ) -> None:
        self._com_step(
            "set_vapour_outlet_temperature",
            lambda: reactor.VapourProduct.Temperature.SetValue(value, unit),
        )
        self._com_step(
            "set_liquid_outlet_temperature",
            lambda: reactor.LiquidProduct.Temperature.SetValue(value, unit),
        )

    def set_outlet_pressure(self, reactor: object, value: float, unit: str) -> None:
        self._com_step(
            "set_vapour_outlet_pressure",
            lambda: reactor.VapourProduct.Pressure.SetValue(value, unit),
        )
        self._com_step(
            "set_liquid_outlet_pressure",
            lambda: reactor.LiquidProduct.Pressure.SetValue(value, unit),
        )

    def set_pressure_drop(self, reactor: object, value: float, unit: str) -> None:
        self._com_step(
            "set_reactor_pressure_drop",
            lambda: reactor.PressureDrop.SetValue(value, unit),
        )

    def _solution_snapshot(self) -> tuple[float, ...]:
        if not self._output_streams:
            raise ValueError("no output streams")
        snapshot: list[float] = []
        outlet_totals = [0.0] * len(self._component_names)
        for stream, _phase in self._output_streams.values():
            if not (_known(stream.Temperature) and _known(stream.Pressure)):
                raise ValueError("outlet conditions are not known")
            snapshot.extend((float(stream.Temperature.GetValue("K")),
                             float(stream.Pressure.GetValue("kPa"))))
            molar = self._values(stream.ComponentMolarFlow, "kgmole/h")
            mass = self._values(stream.ComponentMassFlow, "kg/h")
            if len(molar) != len(outlet_totals) or len(mass) != len(outlet_totals):
                raise ValueError("incomplete outlet component flows")
            snapshot.extend(molar)
            snapshot.extend(mass)
            outlet_totals = [a + b for a, b in zip(outlet_totals, molar, strict=True)]
        if not all(math.isfinite(value) for value in snapshot):
            raise ValueError("non-finite outlet results")
        for component, conversion in self._conversion_targets.items():
            if not self._connected_feeds:
                raise ValueError("conversion verification requires feed")
            index = self._component_names.index(component)
            inlet = sum(self._values(feed.ComponentMolarFlow, "kgmole/h")[index]
                        for feed in self._connected_feeds)
            expected = inlet * (1.0 - conversion)
            outlet = outlet_totals[index]
            actual_conversion = (1.0 - outlet / inlet) if inlet > 0 else None
            self._conversion_checks[component] = {
                "inlet_kmol_h": inlet, "outlet_kmol_h": outlet,
                "expected_outlet_kmol_h": expected, "target_conversion": conversion,
                "actual_conversion": actual_conversion,
            }
            if not math.isfinite(inlet) or not math.isclose(
                outlet, expected, rel_tol=1e-6, abs_tol=1e-6
            ):
                raise ValueError(
                    f"specified conversion not reached: {component}; "
                    f"inlet={inlet:.10g} kmol/h, outlet={outlet:.10g} kmol/h, "
                    f"expected_outlet={expected:.10g} kmol/h, "
                    f"actual_conversion={actual_conversion}, target_conversion={conversion}"
                )
        return tuple(snapshot)

    def solve(self) -> None:
        self._require_case()
        self._com_step(
            "resume_solver",
            lambda: setattr(self.simulation_case.Solver, "CanSolve", True),
        )
        started = time.monotonic()
        deferred_attempted = False
        ui_attempted = False
        deadline = time.monotonic() + self.settings.hysys_run_timeout_seconds
        anchor: tuple[float, ...] | None = None
        stable_since = time.monotonic()
        last_error: Exception | None = None
        try:
            import pythoncom
        except ImportError:
            pythoncom = None
        while time.monotonic() < deadline:
            if pythoncom is not None:
                pythoncom.PumpWaitingMessages()
            conversion_pending = any(
                not math.isclose(check["outlet_kmol_h"], check["expected_outlet_kmol_h"],
                                 rel_tol=1e-6, abs_tol=1e-6)
                for check in self._conversion_checks.values()
            )
            if (self._reactor is not None and time.monotonic() - started >= 1
                    and (conversion_pending or not self._conversion_targets)):
                try:
                    feeds_ready = bool(self._connected_feeds) and all(
                        all(math.isfinite(value) and value >= 0 for value in
                            self._values(feed.ComponentMolarFlow, "kgmole/h"))
                        for feed in self._connected_feeds
                    )
                    if feeds_ready and not deferred_attempted:
                        deferred_attempted = True
                        self._reactor.ActAsSeparatorWhenCannotSolve = False
                        after = self._reactor.ActAsSeparatorWhenCannotSolve
                        self._separator_control = {
                            "method": "com_after_feed_ready", "after": after,
                        }
                    if (feeds_ready and deferred_attempted and not ui_attempted
                            and bool(self._reactor.ActAsSeparatorWhenCannotSolve)
                            and getattr(self._reactor, "_oleobj_", None) is not None):
                        ui_attempted = True
                        from app.hysys.ui_fallback import disable_separator_checkbox

                        activate = getattr(self.simulation_case, "Activate", None)
                        if callable(activate):
                            activate()
                        filename = "conversion.hsc" if self._conversion_targets else ""
                        if self._diagnostic_path is not None:
                            filename = getattr(self, "_case_filename", filename)
                        self._separator_control = disable_separator_checkbox(
                            filename, str(self._reactor.name),
                        )
                        if not self._separator_control["success"]:
                            self._operator_attention_requested = True
                            print(
                                "HYSYS ACTION: Open the CURRENT reactor > Design > Parameters; "
                                "uncheck 'Act as a Separator When Cannot Solve'. "
                                "Keep this script running; results will be checked automatically.",
                                flush=True,
                            )
                except Exception as exc:
                    self._separator_control["error"] = f"{type(exc).__name__}: {exc}"
            try:
                current = self._solution_snapshot()
                if anchor is None or not all(
                    math.isclose(a, b, rel_tol=1e-7, abs_tol=1e-7)
                    for a, b in zip(anchor, current, strict=True)
                ):
                    anchor = current
                    stable_since = time.monotonic()
                elif time.monotonic() - stable_since >= 1.0:
                    return
            except Exception as exc:
                last_error = exc
                anchor = None
            time.sleep(0.1)
        if self._diagnostic_path is not None:
            try:
                self.write_solver_diagnostics(self._diagnostic_path, str(last_error))
            except Exception as diagnostic_error:
                last_error = RuntimeError(
                    f"{last_error}; diagnostic save failed: {type(diagnostic_error).__name__}"
                )
        raise TimeoutError(
            "HYSYS results did not become ready and stable before "
            f"HYSYS_RUN_TIMEOUT_SECONDS; last readiness error: {last_error}"
        ) from last_error

    def write_solver_diagnostics(self, path: Path, readiness_error: str = "") -> dict[str, Any]:
        def safe(operation):
            try:
                return operation()
            except Exception as exc:
                return {"error": f"{type(exc).__name__}: {exc}"}

        def stream_values(stream):
            return {
                "temperature_k": safe(lambda: float(stream.Temperature.GetValue("K"))),
                "pressure_kpa": safe(lambda: float(stream.Pressure.GetValue("kPa"))),
                "molar_flows_kmol_h": safe(lambda: list(
                    self._values(stream.ComponentMolarFlow, "kgmole/h")
                )),
                "mass_flows_kg_h": safe(lambda: list(
                    self._values(stream.ComponentMassFlow, "kg/h")
                )),
            }

        def collection_items(collection):
            count = int(collection.Count)
            if not count:
                return []
            try:
                collection.Item(0)
                start = 0
            except Exception:
                start = 1
            return [collection.Item(index + start) for index in range(count)]

        def reaction_values(reaction):
            return {
                "name": safe(lambda: str(reaction.name)),
                "base_component": safe(lambda: str(reaction.BaseComponent.name)),
                "conversion_coefficients": safe(lambda: list(
                    reaction.ConversionCoefficients.GetValues("")
                )),
                "reactants": safe(lambda: list(reaction.ReactantName.Values)),
                "stoichiometry": safe(lambda: list(reaction.ReactantStoichCoef.GetValues(""))),
            }

        def reactions():
            active = self._reactor.ReactionSet.ActiveReactions
            return [reaction_values(reaction) for reaction in collection_items(active)]

        report = {
            "readiness_error": readiness_error,
            "array_component_order_used": self._component_names,
            "database_component_order": safe(lambda: [str(item.name) for item in
                                                       collection_items(self._component_list.Components)]),
            "conversion_checks": self._conversion_checks,
            "feeds": {str(getattr(stream, "name", index)): stream_values(stream)
                      for index, stream in enumerate(self._connected_feeds)},
            "products": {name: stream_values(stream)
                         for name, (stream, _) in self._output_streams.items()},
            "attached_reactions": safe(reactions),
            "reactor_controls": safe(lambda: collect_reactor_control_properties(self._reactor)),
            "separator_control_attempt": self._separator_control,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    def _values(self, variable: Any, unit: str) -> tuple[float, ...]:
        values = variable.GetValues(unit)
        return tuple(float(item) for item in values)

    def read_case_result(
        self, built_case: BuiltCase, spec: SimulationSpec
    ) -> dict[str, Any]:
        del built_case, spec
        streams: dict[str, dict[str, Any]] = {}
        for name, (stream, phase) in self._output_streams.items():
            fractions = self._values(stream.ComponentMolarFraction, "")
            molar_flows = self._values(stream.ComponentMolarFlow, "kgmole/h")
            mass_flows = self._values(stream.ComponentMassFlow, "kg/h")
            streams[name] = {
                "temperature_k": float(stream.Temperature.GetValue("K")),
                "pressure_kpa": float(stream.Pressure.GetValue("kPa")),
                "phase": phase,
                "composition_basis": "mole",
                "mole_fractions": dict(zip(self._component_names, fractions, strict=True)),
                "molar_flows_kmol_h": dict(
                    zip(self._component_names, molar_flows, strict=True)
                ),
                "mass_flows_kg_h": dict(
                    zip(self._component_names, mass_flows, strict=True)
                ),
            }
        duty = None
        if self._reactor is not None:
            with contextlib.suppress(Exception):
                duty = float(self._reactor.HeatFlow.GetValue("kW"))
        inlets = {}
        for stream in self._connected_feeds:
            inlets[str(stream.name)] = {
                "molar_flows_kmol_h": dict(zip(
                    self._component_names,
                    self._values(stream.ComponentMolarFlow, "kgmole/h"), strict=True,
                )),
                "mass_flows_kg_h": dict(zip(
                    self._component_names,
                    self._values(stream.ComponentMassFlow, "kg/h"), strict=True,
                )),
            }
        validation = validate_stream_balance(inlets, streams)
        return {
            "converged": bool(streams),
            "streams": streams,
            "reactor_duty_kw": duty,
            "warnings": (["operator_attention_requested: HYSYS UI fallback required review"]
                         if self._operator_attention_requested else []),
            "validation": validation,
            "inlet_streams": inlets,
        }

    def close(self) -> None:
        if self.simulation_case is None:
            return
        simulation_case = self.simulation_case
        self.simulation_case = None
        application = self.application
        application_owned = self._application_owned
        self.application = None
        self._application_owned = False
        close_failure: BaseException | None = None
        try:
            self._com_step("close_case", lambda: simulation_case.Close(False))
        except BaseException as exc:
            close_failure = exc
            raise
        finally:
            if application_owned and application is not None:
                try:
                    self._com_step("quit_application", application.Quit)
                except Exception as cleanup_error:
                    if close_failure is None:
                        raise
                    close_failure.add_note(
                        "quitting HYSYS application also failed: "
                        f"{type(cleanup_error).__name__}: {cleanup_error}"
                    )
