"""Start the configured local application and open its browser after it is ready."""

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402


def ready(url: str) -> bool:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url + "/api/health", timeout=1) as response:
            payload = json.load(response)
        return payload.get("app", {}).get("status") == "ok"
    except (OSError, ValueError, urllib.error.URLError):
        return False


def main():
    os.chdir(ROOT)
    settings = Settings()
    host = "127.0.0.1" if settings.app_host in {"0.0.0.0", "127.0.0.1"} else settings.app_host
    url = f"http://{host}:{settings.app_port}"
    if ready(url):
        webbrowser.open(url)
        print(f"Existing workbench opened: {url}")
        return

    def open_when_ready():
        for _ in range(30):
            if ready(url):
                webbrowser.open(url)
                return
            time.sleep(0.5)

    threading.Thread(target=open_when_ready, daemon=True).start()
    print(f"Workbench: {url}\nKeep this window open during the demonstration.", flush=True)
    from scripts.run_server import main as run_server

    run_server()


if __name__ == "__main__":
    main()
