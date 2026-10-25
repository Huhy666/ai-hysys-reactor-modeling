import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.ai.provider import LLMProvider, OpenAICompatibleProvider
from app.api.health import create_health_router
from app.api.runs import create_runs_router
from app.api.specs import create_specs_router
from app.api.workflows import create_workflows_router
from app.config import Settings
from app.hysys.executor import HysysRunExecutor
from app.hysys.v15_adapter import V15HysysAdapter
from app.runs.models import RunExecutor
from app.runs.repository import FileRunRepository
from app.runs.service import RunService
from app.runs.worker import RunWorker


def create_app(
    settings: Settings | None = None,
    *,
    provider: LLMProvider | None = None,
    executor: RunExecutor | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()
    resolved_provider = provider
    if resolved_provider is None and resolved_settings.ai_is_configured:
        resolved_provider = OpenAICompatibleProvider.from_settings(resolved_settings)
    if (
        executor is None
        and resolved_settings.hysys_base_case_path is not None
        and resolved_settings.hysys_base_case_path.is_file()
    ):
        executor = HysysRunExecutor(
            V15HysysAdapter(resolved_settings),
            resolved_settings.hysys_artifact_dir,
        )
    repository = FileRunRepository(resolved_settings.hysys_artifact_dir)
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    service = RunService(repository, queue)
    worker = RunWorker(repository, queue, executor) if executor is not None else None
    web_root = Path(__file__).resolve().parent / "web"

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        repository.recover_incomplete()
        executor_start = getattr(executor, "start", None)
        if executor_start is not None:
            await executor_start()
        if worker is not None:
            await worker.start()
        try:
            yield
        finally:
            if worker is not None:
                await worker.stop()
            executor_stop = getattr(executor, "stop", None)
            if executor_stop is not None:
                await executor_stop()

    app = FastAPI(title="AI HYSYS Web", version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved_settings
    app.state.run_repository = repository
    app.state.run_service = service
    app.state.run_worker = worker
    app.state.llm_provider = resolved_provider
    app.include_router(create_health_router(resolved_settings))
    app.include_router(create_specs_router(resolved_provider))
    app.include_router(create_workflows_router(
        resolved_provider, service, execution_available=executor is not None,
    ))
    app.include_router(create_runs_router(service, execution_available=executor is not None))
    app.mount("/static", StaticFiles(directory=web_root), name="static")

    @app.get("/", include_in_schema=False)
    def web_shell():
        return FileResponse(web_root / "index.html")

    return app


app = create_app()
