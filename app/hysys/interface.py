from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.domain.models import ReactorType, SimulationResult, SimulationSpec
from app.runs.models import RunEvent

EventSink = Callable[[RunEvent], None]


class HysysCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    python_architecture: str
    progid: str
    architecture_compatible: bool
    progid_configured: bool
    dispatch: bool
    version_read: bool
    blank_case: bool
    seed_case: bool = False
    stream_round_trip: bool
    case_save: bool
    hysys_version: str | None = None
    errors: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def all_required(self) -> bool:
        return all(
            (
                self.architecture_compatible,
                self.progid_configured,
                self.dispatch,
                self.version_read,
                self.blank_case or self.seed_case,
                self.stream_round_trip,
                self.case_save,
            )
        )


class HysysSessionInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    progid: str
    owned_by_app: bool
    version: str | None = None


class ConfiguredReactor(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    reactor_type: ReactorType
    name: str
    com_object: object | None = None


class HysysAdapter(Protocol):
    def probe(self) -> HysysCapabilities: ...

    def start_owned_session(self) -> HysysSessionInfo: ...

    def build_and_run(
        self,
        spec: SimulationSpec,
        run_dir: Path,
        event_sink: EventSink,
    ) -> SimulationResult: ...

    def close_owned_session(self) -> None: ...
