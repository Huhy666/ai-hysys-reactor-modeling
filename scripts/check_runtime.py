"""Check loaded project paths, unit compatibility and an optional running service."""

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.domain import units  # noqa: E402
from app.domain.models import Quantity  # noqa: E402
from app.hysys import conversion  # noqa: E402
from app.runtime import source_build_id  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="Optional local service URL, e.g. http://127.0.0.1:8000")
    args = parser.parse_args()
    build_id = source_build_id()
    print(f"Project: {ROOT}\nPython: {sys.executable}\nSource build: {build_id}")
    print(f"Units module: {units.__file__}\nConversion module: {conversion.__file__}")
    try:
        pressure = units.convert_quantity(Quantity(value=1000, unit="kPa abs"), "kPa")
        if pressure.value != 1000:
            raise ValueError("absolute-pressure normalization changed the value")
        print("PASS unit compatibility: 1000 kPa abs -> 1000 kPa")
        if args.url:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(args.url.rstrip("/") + "/api/runtime", timeout=5) as response:
                running = json.load(response)
            print(f"Running build: {running.get('build_id', 'unavailable')}")
            if running.get("build_id") != build_id:
                raise ValueError(
                    "running service differs from source; stop the old service and restart"
                )
            print("PASS source and running-service identities match")
    except (OSError, ValueError, urllib.error.URLError) as exc:
        print(f"FAIL runtime check: {exc}")
        return 1
    print("This checks source/runtime compatibility, not real AI or HYSYS execution.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
