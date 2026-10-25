from app.config import Settings


def test_settings_load_non_secret_defaults(monkeypatch):
    for name in (
        "APP_HOST",
        "APP_PORT",
        "APP_ENV",
        "LLM_PROVIDER",
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL",
        "LLM_TIMEOUT_SECONDS",
        "LLM_MAX_RETRIES",
        "HYSYS_VISIBLE",
        "HYSYS_BASE_CASE_PATH",
        "HYSYS_RUN_TIMEOUT_SECONDS",
        "HYSYS_ARTIFACT_DIR",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.app_host == "127.0.0.1"
    assert settings.app_port == 8000
    assert settings.app_env == "development"
    assert settings.llm_api_key is None
    assert settings.hysys_visible is True
    assert settings.hysys_base_case_path is None
    assert settings.hysys_artifact_dir.name == "runs"


def test_settings_load_hysys_base_case_path(monkeypatch, tmp_path):
    base_case = tmp_path / "base-case.hsc"
    monkeypatch.setenv("HYSYS_BASE_CASE_PATH", str(base_case))

    settings = Settings(_env_file=None)

    assert settings.hysys_base_case_path == base_case
