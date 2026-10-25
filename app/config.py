from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed application settings with secret-safe values."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_env: str = "development"

    llm_provider: str = "openai"
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str | None = None
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2

    hysys_visible: bool = True
    hysys_progid: str = "HYSYS.Application"
    hysys_base_case_path: Path | None = None
    hysys_probe_result_path: Path | None = None
    hysys_run_timeout_seconds: float = 300.0
    hysys_artifact_dir: Path = Path("runs")

    log_level: str = "INFO"

    @property
    def ai_is_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)
