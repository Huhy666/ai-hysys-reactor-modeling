from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_root_serves_complete_chinese_workflow_shell(tmp_path):
    client = TestClient(
        create_app(Settings(hysys_artifact_dir=tmp_path, _env_file=None))
    )

    response = client.get("/")

    assert response.status_code == 200
    for landmark in (
        "AI HYSYS",
        "自然语言需求",
        "规格审查",
        "运行进度",
        "模拟结果",
        "运行历史",
        "甲烷蒸汽重整",
        "甲苯歧化",
    ):
        assert landmark in response.text
    assert 'id="modeling-request"' in response.text
    assert 'id="spec-json"' in response.text
    assert 'id="confirm-button"' in response.text
    assert 'id="run-button"' in response.text
    assert 'id="run-state"' in response.text
    assert 'href="/static/styles.css"' in response.text
    assert 'src="/static/app.js"' in response.text


def test_static_assets_are_local_and_served(tmp_path):
    client = TestClient(
        create_app(Settings(hysys_artifact_dir=tmp_path, _env_file=None))
    )

    css = client.get("/static/styles.css")
    javascript = client.get("/static/app.js")

    assert css.status_code == 200
    assert javascript.status_code == 200
    assert "https://" not in css.text
    assert "fetch(" in javascript.text
    assert "总流量 3700 kmol/h" in javascript.text
    assert "Methane=0.27027027" in javascript.text
    assert "压降均为 0 kPa" in javascript.text
