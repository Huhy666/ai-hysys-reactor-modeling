from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from uuid import uuid4

from app.domain.models import ReactorDecision, SimulationResult, SimulationSpec
from app.runs.models import RunEvent, RunRecord, RunState, utc_now

_INTERRUPTED_STATES = {
    RunState.QUEUED,
    RunState.CONNECTING,
    RunState.BUILDING_CASE,
    RunState.SOLVING,
    RunState.READING_RESULTS,
    RunState.VALIDATING,
}


class FileRunRepository:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.load_errors: list[str] = []

    def _run_dir(self, run_id: str) -> Path:
        return self.root / run_id

    @staticmethod
    def _atomic_json(path: Path, payload: object) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, path)

    def _write_record(self, record: RunRecord) -> None:
        self._atomic_json(
            self._run_dir(record.id) / "run.json",
            record.model_dump(mode="json"),
        )

    def create(
        self,
        spec: SimulationSpec,
        decision: ReactorDecision,
        *,
        run_id: str | None = None,
        original_request: dict[str, object] | None = None,
        initial_state: RunState = RunState.DRAFT,
    ) -> RunRecord:
        record = RunRecord(
            id=run_id or uuid4().hex,
            state=initial_state,
            spec=spec,
            decision=decision,
        )
        run_dir = self._run_dir(record.id)
        run_dir.mkdir(parents=True, exist_ok=False)
        self._atomic_json(run_dir / "request.json", original_request or {})
        self._atomic_json(run_dir / "normalized-spec.json", spec.model_dump(mode="json"))
        self._atomic_json(run_dir / "decision.json", decision.model_dump(mode="json"))
        self._write_record(record)
        (run_dir / "events.jsonl").touch()
        return record

    def get(self, run_id: str) -> RunRecord:
        path = self._run_dir(run_id) / "run.json"
        return RunRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self) -> list[RunRecord]:
        self.load_errors = []
        records: list[RunRecord] = []
        for directory in sorted(path for path in self.root.iterdir() if path.is_dir()):
            try:
                records.append(self.get(directory.name))
            except Exception as exc:
                self.load_errors.append(f"{directory.name}: {type(exc).__name__}")
        return sorted(records, key=lambda record: (record.created_at, record.id))

    def update_state(
        self,
        run_id: str,
        state: RunState,
        *,
        error: str | None = None,
        recoverable: bool | None = None,
        cancel_requested: bool | None = None,
    ) -> RunRecord:
        record = self.get(run_id)
        record.state = state
        record.updated_at = utc_now()
        if error is not None:
            record.error = error
        if recoverable is not None:
            record.recoverable = recoverable
        if cancel_requested is not None:
            record.cancel_requested = cancel_requested
        self._write_record(record)
        return record

    def append_event(self, run_id: str, event: RunEvent) -> None:
        path = self._run_dir(run_id) / "events.jsonl"
        with path.open("a", encoding="utf-8") as stream:
            stream.write(event.model_dump_json() + "\n")

    def save_result(self, run_id: str, result: SimulationResult) -> RunRecord:
        record = self.get(run_id)
        record.result = result
        record.updated_at = utc_now()
        self._atomic_json(
            self._run_dir(run_id) / "result.json",
            result.model_dump(mode="json"),
        )
        csv_path = self._run_dir(run_id) / "streams.csv"
        with csv_path.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.writer(output)
            writer.writerow([
                "stream", "phase", "temperature_K", "pressure_kPa_abs", "component",
                "mole_fraction", "molar_flow_kmol_h", "mass_flow_kg_h",
            ])
            for name, stream in result.streams.items():
                for component, flow in stream.get("molar_flows_kmol_h", {}).items():
                    writer.writerow([
                        name, stream.get("phase"), stream.get("temperature_k"),
                        stream.get("pressure_kpa"), component,
                        stream.get("mole_fractions", {}).get(component), flow,
                        stream.get("mass_flows_kg_h", {}).get(component),
                    ])
        self._write_record(record)
        return record

    def recover_incomplete(self) -> list[RunRecord]:
        recovered: list[RunRecord] = []
        for record in self.list():
            if record.state in _INTERRUPTED_STATES:
                recovered.append(
                    self.update_state(
                        record.id,
                        RunState.FAILED,
                        error="application_restarted_during_run",
                        recoverable=True,
                    )
                )
        return recovered
