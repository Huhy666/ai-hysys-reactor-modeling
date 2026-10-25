from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.ai.parser import parse_request
from app.ai.provider import LLMProvider
from app.domain.models import Severity, SimulationSpec, ValidationIssue
from app.domain.reactor_selection import select_reactor
from app.domain.spec_normalization import expand_confirmed_xylene_group
from app.runs.service import RunService


class WorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=20000)


def create_workflows_router(
    provider: LLMProvider | None,
    service: RunService,
    *, execution_available: bool = True,
) -> APIRouter:
    router = APIRouter(prefix="/api/workflows", tags=["workflows"])

    @router.post("/submit")
    async def submit(request: WorkflowRequest):
        if provider is None:
            raise HTTPException(
                status_code=503,
                detail="language-model provider is not configured",
            )
        parsed = await parse_request(request.text, provider)
        if parsed.spec is None:
            return {
                "spec": None,
                "decision": None,
                "issues": [issue.model_dump(mode="json") for issue in parsed.issues],
                "executable": False,
                "run": None,
                "raw_provider_id": parsed.raw_provider_id,
            }

        parsed.spec = expand_confirmed_xylene_group(parsed.spec)
        decision = select_reactor(parsed.spec)
        prepared = None
        if decision.reactor_type is not None:
            prepared = SimulationSpec.model_validate(
                parsed.spec.model_dump()
                | {
                    "title": parsed.spec.title or "未命名反应",
                    "reactor_type": decision.reactor_type,
                }
            )
        issues = [*parsed.issues, *decision.blocking_issues]
        if not execution_available:
            issues.append(ValidationIssue(
                code="hysys_executor_unavailable", field="environment", severity=Severity.BLOCKING,
                message="HYSYS执行器未就绪，请检查基础案例路径和远程配置",
            ))
        run = None
        if prepared is not None and not issues:
            run = service.create_run(
                prepared,
                decision,
                original_request={"text": request.text},
            )
            run = service.enqueue(run.id)

        return {
            "spec": prepared.model_dump(mode="json") if prepared else None,
            "decision": decision.model_dump(mode="json"),
            "issues": [issue.model_dump(mode="json") for issue in issues],
            "executable": prepared is not None and not issues,
            "run": run.model_dump(mode="json") if run else None,
            "raw_provider_id": parsed.raw_provider_id,
        }

    return router
