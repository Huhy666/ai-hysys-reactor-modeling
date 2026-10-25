"""Real browser + API + builders, with explicit test-only AI and COM boundaries."""

import json
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.domain.demo_specs import generalization_specs  # noqa: E402
from app.main import create_app  # noqa: E402
from tests.contract.test_web_generic_pipeline import GenericWebExecutor  # noqa: E402
from tests.contract.test_workflow_api import StaticProvider  # noqa: E402


def main():
    with TemporaryDirectory(prefix="hysys-web-recording-test-") as directory:
        root = Path(directory)
        provider = StaticProvider({})
        executor = GenericWebExecutor(root)
        app = create_app(
            Settings(hysys_artifact_dir=root, _env_file=None),
            provider=provider, executor=executor,
        )
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.02)
            assert server.started
            with sync_playwright() as playwright:
                edge = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / (
                    r"Microsoft\Edge\Application\msedge.exe"
                )
                browser = playwright.chromium.launch(executable_path=str(edge), headless=True)
                page = browser.new_page(viewport={"width": 1360, "height": 900})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                for name, spec in generalization_specs().items():
                    provider.payload = spec.model_dump(mode="json", exclude={"reactor_type"})
                    provider.payload["feeds"][0]["pressure"]["unit"] = "kPa abs"
                    page.goto(f"http://127.0.0.1:{port}")
                    page.wait_for_load_state("networkidle")
                    page.locator("#modeling-request").fill(f"New reaction: {name}")
                    page.locator("#parse-button").click()
                    page.wait_for_function(
                        "document.querySelector('#spec-json').value.includes('known_conversion')"
                    )
                    draft = json.loads(page.locator("#spec-json").input_value())
                    assert draft["reactor_type"] == "conversion"
                    assert any(not a["confirmed"] for a in draft["assumptions"])
                    assert "assumptions" in page.locator("#issues").inner_text()
                    page.locator("#confirm-button").click()
                    page.wait_for_function(
                        "document.querySelector('#run-state').textContent === 'succeeded'"
                    )
                    assert "测试 / 降级数据" in page.locator("#result-body").inner_text()
                    assert page.locator("#result-downloads a").count() == 2
                    print(f"PASS browser/API/builders: {name}; source remains fake")
                assert len(executor.sessions) == 3
                assert not errors, errors
                browser.close()
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(f"http://127.0.0.1:{port}/api/runtime") as response:
                assert len(json.load(response)["build_id"]) == 12
            print("Software regression only: no real LLM or HYSYS was invoked.")
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            listener.close()


if __name__ == "__main__":
    main()
