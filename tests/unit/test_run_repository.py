from app.domain.models import (
    ComponentSpec,
    Quantity,
    ReactorDecision,
    ReactorType,
    SimulationSpec,
    StreamSpec,
)
from app.runs.models import RunState
from app.runs.repository import FileRunRepository


def _spec():
    return SimulationSpec(
        title="repository test",
        reactor_type=ReactorType.CONVERSION,
        components=[ComponentSpec(user_name="Methane", hysys_name="Methane")],
        feeds=[
            StreamSpec(
                name="Feed",
                temperature=Quantity(value=300, unit="K"),
                pressure=Quantity(value=100, unit="kPa"),
                total_flow=Quantity(value=1, unit="kmol/h"),
                flow_basis="molar",
                composition={"Methane": 1.0},
            )
        ],
        known_conversion=0.5,
    )


def _decision():
    return ReactorDecision(
        reactor_type=ReactorType.CONVERSION,
        reason_codes=["KNOWN_CONVERSION"],
        explanation="known conversion",
    )


def test_create_run_writes_traceable_files_atomically(tmp_path):
    repository = FileRunRepository(tmp_path)

    run = repository.create(
        _spec(),
        _decision(),
        run_id="run-ok",
        original_request={"text": "simulate"},
    )

    run_dir = tmp_path / run.id
    assert {path.name for path in run_dir.iterdir()} == {
        "request.json",
        "normalized-spec.json",
        "decision.json",
        "run.json",
        "events.jsonl",
    }
    assert not list(run_dir.glob("*.tmp"))


def test_list_survives_repository_reinstantiation(tmp_path):
    FileRunRepository(tmp_path).create(_spec(), _decision(), run_id="run-one")

    records = FileRunRepository(tmp_path).list()

    assert [record.id for record in records] == ["run-one"]


def test_corrupt_record_is_reported_without_hiding_valid_history(tmp_path):
    repository = FileRunRepository(tmp_path)
    repository.create(_spec(), _decision(), run_id="valid-run")
    corrupt = tmp_path / "corrupt-run"
    corrupt.mkdir()
    (corrupt / "run.json").write_text("{broken", encoding="utf-8")

    records = repository.list()

    assert [record.id for record in records] == ["valid-run"]
    assert any("corrupt-run" in error for error in repository.load_errors)


def test_recover_incomplete_marks_interrupted_run_failed(tmp_path):
    repository = FileRunRepository(tmp_path)
    repository.create(_spec(), _decision(), run_id="interrupted")
    repository.update_state("interrupted", RunState.SOLVING)

    recovered = FileRunRepository(tmp_path).recover_incomplete()

    assert [record.id for record in recovered] == ["interrupted"]
    record = FileRunRepository(tmp_path).get("interrupted")
    assert record.state is RunState.FAILED
    assert record.recoverable is True
    assert record.error == "application_restarted_during_run"

