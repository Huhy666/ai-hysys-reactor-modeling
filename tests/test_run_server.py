import subprocess
import sys
from pathlib import Path


def test_launcher_imports_app_when_started_outside_project_root(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    launcher = project_root / "scripts" / "run_server.py"
    command = [
        sys.executable,
        "-c",
        f"import runpy; runpy.run_path({str(launcher)!r}, run_name='launcher_test')",
    ]

    completed = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)

    assert completed.returncode == 0, completed.stderr
