import os

import pytest

from app.config import Settings
from scripts.probe_hysys import run_probe


@pytest.mark.hysys
def test_hysys_v15_capability_probe(tmp_path):
    if os.getenv("HYSYS_INTEGRATION_ENABLED", "").lower() not in {"1", "true", "yes"}:
        pytest.skip("HYSYS integration disabled")

    report = run_probe(Settings(), tmp_path / "probe-result.json")

    assert report.all_required
    assert report.output_path == tmp_path / "probe-result.json"

