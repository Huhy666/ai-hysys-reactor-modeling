"""Package only source and documentation; exclude local configuration and run data."""

from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]


def main():
    paths = []
    extensions = {".py", ".ps1", ".html", ".js", ".css", ".md", ".pdf", ".svg"}
    for directory in ("app", "scripts", "tests", "docs"):
        paths.extend(path for path in (ROOT / directory).rglob("*")
                     if path.is_file() and path.suffix in extensions
                     and (directory != "docs" or path.name in {
                         "report.md", "report.pdf", "demo-script.md",
                         "remote-acceptance.md", "conversion-readback.md",
                         "getting-started.md", "architecture.md", "web-demo.md",
                         "api.md", "validation.md", "troubleshooting.md",
                         "project-banner.svg",
                     })
                     and "__pycache__" not in path.parts)
    paths.extend(ROOT / name for name in (
        "README.md", "pyproject.toml", ".env.example", ".gitignore",
        "CONTRIBUTING.md", ".editorconfig",
        "run_toluene_check.cmd", "run_full_acceptance.cmd",
        "run_deadline_acceptance.cmd", "inspect_conversion_case.cmd",
        "start_web.cmd", "run_generalization.cmd",
    ))
    paths.extend(path for path in (ROOT / ".github").rglob("*")
                 if path.is_file() and path.suffix in {".md", ".yml"})
    output = ROOT / "dist" / (
        "ai-hysys-remote-update-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".zip"
    )
    output.parent.mkdir(exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            archive.write(path, path.relative_to(ROOT).as_posix())
    with ZipFile(output) as archive:
        names = archive.namelist()
        assert all(not name.endswith((".rdp", ".hsc", ".log")) for name in names)
        assert ".env" not in names
        assert not any(name.startswith(("runs/", ".venv/")) for name in names)
    print(output)
    print(f"Packaged {len(paths)} source/documentation files; no credentials or cases.")


if __name__ == "__main__":
    main()
