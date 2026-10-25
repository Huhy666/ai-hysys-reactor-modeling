import platform
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.config import Settings
from app.domain.models import ReactorType, SimulationResult, SimulationSpec
from app.domain.spec_normalization import expand_confirmed_xylene_group
from app.hysys.case_builder import build_base_case
from app.hysys.conversion import configure_conversion_case
from app.hysys.equilibrium import configure_equilibrium_case
from app.hysys.interface import EventSink, HysysCapabilities, HysysSessionInfo
from app.hysys.result_reader import read_result
from app.hysys.v15_session import V15CaseSession
from app.runs.models import RunEvent, RunState


def _dispatch_new(progid: str):
    from win32com.client import DispatchEx

    return DispatchEx(progid)


class V15HysysAdapter:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        application: Any | None = None,
        owned_by_app: bool = False,
        session_factory: Callable[..., V15CaseSession] = V15CaseSession,
    ) -> None:
        self.settings = settings or Settings()
        self._application = application
        self.owned_by_app = owned_by_app
        self._session_factory = session_factory

    def probe(self) -> HysysCapabilities:
        errors: list[str] = []
        dispatched = False
        version_read = False
        version = None
        application = None
        try:
            application = _dispatch_new(self.settings.hysys_progid)
            dispatched = True
            version = str(application.Version)
            version_read = bool(version)
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            if application is not None:
                try:
                    application.Quit()
                except Exception as exc:
                    errors.append(f"close: {type(exc).__name__}: {exc}")
        return HysysCapabilities(
            python_architecture=platform.architecture()[0],
            progid=self.settings.hysys_progid,
            architecture_compatible=platform.architecture()[0] == "64bit",
            progid_configured=bool(self.settings.hysys_progid),
            dispatch=dispatched,
            version_read=version_read,
            blank_case=False,
            stream_round_trip=False,
            case_save=False,
            hysys_version=version,
            errors=errors,
        )

    def start_owned_session(self) -> HysysSessionInfo:
        if self._application is not None or self.owned_by_app:
            raise RuntimeError("a HYSYS application is already attached")
        # V15 rejects opening a copied .hsc through its file moniker when a
        # DispatchEx-created application is already active. The verified path is
        # to let GetObject(case_path) create the application together with the
        # first case, so this lifecycle marker deliberately performs no dispatch.
        self.owned_by_app = True
        return HysysSessionInfo(
            progid=self.settings.hysys_progid,
            owned_by_app=True,
            version=None,
        )

    def build_and_run(
        self,
        spec: SimulationSpec,
        run_dir: Path,
        event_sink: EventSink,
    ) -> SimulationResult:
        spec = expand_confirmed_xylene_group(spec)
        run_dir = Path(run_dir).resolve()
        run_dir.mkdir(parents=True, exist_ok=True)
        event_sink(RunEvent(state=RunState.CONNECTING, message="connected to HYSYS V15"))

        if spec.reactor_type is ReactorType.CONVERSION:
            result = self._run_case(
                spec,
                run_dir / "conversion.hsc",
                event_sink,
                lambda built: configure_conversion_case(built, spec, event_sink),
            )
        elif spec.reactor_type is ReactorType.EQUILIBRIUM:
            case_results: list[tuple[str, SimulationResult]] = []
            for case_index, operating_case in enumerate(spec.operating_cases, start=1):
                safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", operating_case.name)
                safe_name = safe_name.strip("-.") or "case"
                case_result = self._run_case(
                    spec,
                    run_dir / f"equilibrium-{case_index:02d}-{safe_name}.hsc",
                    event_sink,
                    lambda built, item=operating_case: configure_equilibrium_case(
                        built, spec, item, event_sink
                    ),
                )
                case_results.append((operating_case.name, case_result))
            result = self._combine_case_results(run_dir.name, case_results)
        else:
            raise NotImplementedError(
                f"real HYSYS execution is not implemented for {spec.reactor_type.value}"
            )

        event_sink(
            RunEvent(
                state=RunState.VALIDATING,
                message="validating HYSYS result payload",
            )
        )
        return result

    def _run_case(
        self,
        spec: SimulationSpec,
        case_path: Path,
        event_sink: EventSink,
        configure: Callable[[Any], Any],
    ) -> SimulationResult:
        session = self._session_factory(self.settings, application=self._application)
        primary_failure: BaseException | None = None
        try:
            built = build_base_case(session, spec, case_path, event_sink)
            configure(built)
            event_sink(
                RunEvent(state=RunState.SOLVING, message=f"solving {case_path.name}")
            )
            session.solve()
            session.save_case(case_path)
            event_sink(
                RunEvent(
                    state=RunState.READING_RESULTS,
                    message=f"reading {case_path.name}",
                )
            )
            return read_result(built, spec)
        except BaseException as exc:
            primary_failure = exc
            if getattr(session, "simulation_case", None) is not None:
                try:
                    session.save_case(case_path)
                except Exception as save_error:
                    exc.add_note(f"partial case save failed: {type(save_error).__name__}")
            raise
        finally:
            try:
                session.close()
            except Exception as cleanup_error:
                if primary_failure is None:
                    raise
                primary_failure.add_note(
                    "HYSYS cleanup also failed: "
                    f"{type(cleanup_error).__name__}: {cleanup_error}"
                )

    @staticmethod
    def _combine_case_results(
        run_id: str, case_results: list[tuple[str, SimulationResult]]
    ) -> SimulationResult:
        streams = {}
        case_paths = []
        warnings = []
        duties = []
        versions = []
        for case_name, result in case_results:
            case_paths.extend(result.case_paths)
            warnings.extend(f"{case_name}: {item}" for item in result.warnings)
            streams.update(
                {f"{case_name}/{name}": value for name, value in result.streams.items()}
            )
            if result.reactor_duty_kw is not None:
                duties.append(result.reactor_duty_kw)
            if result.hysys_version:
                versions.append(result.hysys_version)
        return SimulationResult(
            run_id=run_id,
            source="hysys",
            converged=bool(case_results)
            and all(result.converged for _, result in case_results),
            hysys_version=versions[0] if versions else None,
            case_paths=case_paths,
            streams=streams,
            reactor_duty_kw=sum(duties) if duties else None,
            warnings=warnings,
            validation={name: result.validation for name, result in case_results},
            inlet_streams={
                f"{name}/{feed}": stream
                for name, result in case_results for feed, stream in result.inlet_streams.items()
            },
        )

    def close_owned_session(self) -> None:
        if not self.owned_by_app:
            return
        application = self._application
        self._application = None
        self.owned_by_app = False
        if application is not None:
            application.Quit()
