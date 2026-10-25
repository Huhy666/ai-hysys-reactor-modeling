"""Manual browser regression. Requires playwright; all result values are test fixtures."""

import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    with sync_playwright() as playwright:
        edge = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / (
            r"Microsoft\Edge\Application\msedge.exe"
        )
        browser = playwright.chromium.launch(executable_path=str(edge), headless=True)
        page = browser.new_page(viewport={"width": 1360, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        fake = {
            "id": "browser-test", "state": "succeeded", "updated_at": "2026-10-25T00:00:00Z",
            "spec": {"title": "<img src=x onerror=alert(1)> 浏览器测试", "assumptions": []},
            "result": {
                "source": "fake", "converged": True, "case_paths": [r"C:\test\case.hsc"],
                "validation": {}, "reactor_duty_kw": 0,
                "streams": {"Test Product": {
                    "temperature_k": 650, "pressure_kpa": 2500, "phase": "gas",
                    "molar_flows_kmol_h": {"Toluene": 50},
                    "mole_fractions": {"Toluene": 0.5},
                    "mass_flows_kg_h": {"Toluene": 4607},
                }},
            },
        }

        def mock_history(route):
            route.fulfill(status=200, content_type="application/json", body=json.dumps([fake]))

        page.route("**/api/runs", mock_history)
        page.goto("http://127.0.0.1:8000")
        page.wait_for_load_state("networkidle")
        assert page.locator("#connection-status").inner_text()
        page.get_by_role("button", name="填入：甲苯歧化").click()
        assert "10000" in page.locator("#modeling-request").input_value()
        page.locator("#history-list button").click()
        assert page.locator("#history-list img").count() == 0
        assert "测试 / 降级数据" in page.locator("#result-body").inner_text()
        assert page.locator("#result-body table tbody tr").count() == 1
        assert page.locator("#result-downloads a").count() == 3
        assert page.locator("#result-downloads a").last.get_attribute("href").endswith("case.hsc")
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.locator("#result-downloads").is_visible()
        assert not errors, errors
        output = Path("runs/browser-check.png")
        output.parent.mkdir(exist_ok=True)
        page.screenshot(path=str(output), full_page=True)
        browser.close()
        print("PASS: sample input, safe history, test-source banner, table, downloads, mobile")


if __name__ == "__main__":
    main()
