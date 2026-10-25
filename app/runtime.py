"""Identify the source loaded at service startup without exposing configuration."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

SOURCE_FILES = (
    "main.py", "runtime.py", "api/health.py", "api/workflows.py", "api/specs.py",
    "ai/parser.py", "domain/models.py", "domain/units.py", "domain/validation.py",
    "domain/reactor_selection.py", "domain/spec_normalization.py",
    "hysys/case_builder.py", "hysys/conversion.py", "hysys/equilibrium.py",
    "hysys/v15_adapter.py", "hysys/v15_session.py", "web/app.js", "web/index.html",
)


def source_build_id(root: Path | None = None) -> str:
    root = root or Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for relative in SOURCE_FILES:
        digest.update(relative.encode("utf-8"))
        path = root / relative
        content = path.read_text(encoding="utf-8") if path.is_file() else "<missing>"
        digest.update(content.replace("\r\n", "\n").encode("utf-8"))
    return digest.hexdigest()[:12]


def runtime_identity() -> dict[str, str]:
    return {
        "build_id": source_build_id(),
        "started_at": datetime.now(UTC).isoformat(),
        "identity_kind": "startup_source_snapshot",
    }
