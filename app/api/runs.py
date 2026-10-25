from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict

from app.domain.models import SimulationSpec
from app.domain.reactor_selection import select_reactor
from app.domain.spec_normalization import expand_confirmed_xylene_group
from app.runs.service import RunService


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: SimulationSpec
    original_text: str | None = None
    auto_start: bool = False


def _not_found(run_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"run not found: {run_id}")


def create_runs_router(service: RunService, *, execution_available: bool = True) -> APIRouter:
    router = APIRouter(prefix="/api/runs", tags=["runs"])

    @router.post("", status_code=201)
    async def create_run(request: CreateRunRequest):
        if request.auto_start and not execution_available:
            raise HTTPException(
                status_code=503, detail="HYSYS执行器未就绪，请检查基础案例路径和远程配置",
            )
        request.spec = expand_confirmed_xylene_group(request.spec)
        decision = select_reactor(request.spec)
        record = service.create_run(
            request.spec,
            decision,
            original_request={"text": request.original_text or ""},
        )
        if request.auto_start and record.state.value == "ready":
            record = service.enqueue(record.id)
        return record

    @router.get("")
    def list_runs():
        return service.list_runs()

    @router.get("/{run_id}")
    def get_run(run_id: str):
        try:
            return service.get(run_id)
        except (FileNotFoundError, NotADirectoryError):
            raise _not_found(run_id) from None

    @router.post("/{run_id}/cancel")
    def cancel_run(run_id: str):
        try:
            return service.cancel(run_id)
        except (FileNotFoundError, NotADirectoryError):
            raise _not_found(run_id) from None

    @router.get("/{run_id}/events")
    def stream_events(run_id: str):
        try:
            service.get(run_id)
        except (FileNotFoundError, NotADirectoryError):
            raise _not_found(run_id) from None
        events_path = service.repository.root / run_id / "events.jsonl"

        def events():
            for line in events_path.read_text(encoding="utf-8").splitlines():
                if line:
                    yield f"data: {line}\n\n"
            current = service.get(run_id)
            yield f"data: {current.model_dump_json()}\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    @router.get("/{run_id}/artifacts/{filename}")
    def download_artifact(run_id: str, filename: str):
        try:
            service.get(run_id)
        except (FileNotFoundError, NotADirectoryError):
            raise _not_found(run_id) from None
        if Path(filename).name != filename or filename in {"", ".", ".."}:
            raise HTTPException(status_code=400, detail="invalid artifact path")
        run_dir = (service.repository.root / run_id).resolve()
        artifact = (run_dir / filename).resolve()
        if not artifact.is_relative_to(run_dir) or not artifact.is_file():
            raise HTTPException(status_code=404, detail="artifact not found")
        if artifact.suffix.lower() not in {".json", ".jsonl", ".csv", ".hsc"}:
            raise HTTPException(status_code=400, detail="artifact type is not allowed")
        return FileResponse(artifact, filename=artifact.name)

    return router
