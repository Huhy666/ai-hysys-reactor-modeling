from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.ai.parser import parse_request
from app.ai.provider import LLMProvider
from app.domain.models import DraftSimulationSpec, SimulationSpec
from app.domain.reactor_selection import select_reactor
from app.domain.spec_normalization import expand_confirmed_xylene_group
from app.domain.validation import validate_spec


class NaturalLanguageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=20000)


def create_specs_router(provider: LLMProvider | None) -> APIRouter:
    router = APIRouter(prefix="/api/specs", tags=["specifications"])

    @router.post("/parse")
    async def parse_modeling_request(request: NaturalLanguageRequest):
        if provider is None:
            raise HTTPException(
                status_code=503,
                detail="language-model provider is not configured",
            )
        return await parse_request(request.text, provider)

    @router.post("/validate")
    def validate_modeling_spec(spec: SimulationSpec):
        spec = expand_confirmed_xylene_group(spec)
        decision = select_reactor(spec)
        issues = validate_spec(spec)
        return {
            "spec": spec.model_dump(mode="json"),
            "decision": decision.model_dump(mode="json"),
            "issues": [issue.model_dump(mode="json") for issue in issues],
            "executable": not issues and not decision.blocking_issues,
        }

    @router.post("/prepare")
    def prepare_modeling_spec(draft: DraftSimulationSpec):
        draft = expand_confirmed_xylene_group(draft)
        decision = select_reactor(draft)
        prepared = None
        if decision.reactor_type is not None:
            prepared = SimulationSpec.model_validate(
                draft.model_dump()
                | {
                    "title": draft.title or "未命名反应",
                    "reactor_type": decision.reactor_type,
                }
            )
        issues = decision.blocking_issues
        return {
            "spec": prepared.model_dump(mode="json") if prepared else None,
            "draft": draft.model_dump(mode="json"),
            "decision": decision.model_dump(mode="json"),
            "issues": [issue.model_dump(mode="json") for issue in issues],
            "executable": prepared is not None and not issues,
        }

    return router
