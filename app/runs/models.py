from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import ReactorDecision, SimulationResult, SimulationSpec


def utc_now() -> datetime:
    return datetime.now(UTC)


class RunState(StrEnum):
    DRAFT = "draft"
    NEEDS_CLARIFICATION = "needs_clarification"
    READY = "ready"
    QUEUED = "queued"
    CONNECTING = "connecting"
    BUILDING_CASE = "building_case"
    SOLVING = "solving"
    READING_RESULTS = "reading_results"
    VALIDATING = "validating"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime = Field(default_factory=utc_now)
    state: RunState
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    state: RunState
    spec: SimulationSpec
    decision: ReactorDecision
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    cancel_requested: bool = False
    recoverable: bool = False
    error: str | None = None
    result: SimulationResult | None = None


EventSink = Callable[[RunState, str, dict[str, Any] | None], Awaitable[None]]
CancellationCheck = Callable[[], bool]


class RunExecutor(Protocol):
    async def execute(
        self,
        run: RunRecord,
        event_sink: EventSink,
        cancellation_requested: CancellationCheck,
    ) -> SimulationResult | None: ...
