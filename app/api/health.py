import json

from fastapi import APIRouter

from app.config import Settings


def create_health_router(settings: Settings) -> APIRouter:
    router = APIRouter()

    def hysys_status() -> dict[str, str]:
        path = settings.hysys_probe_result_path
        if path is None or not path.is_file():
            return {"status": "not_probed"}
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"status": "probe_report_invalid"}
        capabilities = report.get("capabilities", report)
        ready = bool(report.get("all_required", capabilities.get("all_required", False)))
        version = capabilities.get("hysys_version") or report.get("version")
        status = {"status": "ready" if ready else "probe_failed"}
        if isinstance(version, str) and version:
            status["version"] = version
        return status

    @router.get("/api/health")
    def get_health() -> dict[str, dict[str, str]]:
        return {
            "app": {"status": "ok", "environment": settings.app_env},
            "ai": {
                "status": "configured" if settings.ai_is_configured else "not_configured",
                "provider": settings.llm_provider,
            },
            "hysys": hysys_status(),
        }

    return router
