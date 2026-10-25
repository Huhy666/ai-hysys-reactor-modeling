import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.ai.provider import LLMProvider, ProviderTimeoutError
from app.domain.models import (
    DraftSimulationSpec,
    OperatingCaseSpec,
    Quantity,
    ReactorType,
    Severity,
    SourceKind,
    ValidationIssue,
)
from app.domain.units import canonical_unit
from app.hysys.component_mapping import COMPONENT_ALIASES, resolve_component


class ParseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: DraftSimulationSpec | None = None
    issues: list[ValidationIssue] = Field(default_factory=list)
    raw_provider_id: str | None = None


def _issue(code: str, message: str) -> ValidationIssue:
    return ValidationIssue(code=code, field="request", severity=Severity.BLOCKING, message=message)


def _mark_ai_sources(spec: DraftSimulationSpec) -> None:
    for assumption in spec.assumptions:
        assumption.confirmed = False
    for component in spec.components:
        component.source = SourceKind.AI_EXTRACTED
    for feed in spec.feeds:
        for quantity in (feed.temperature, feed.pressure, feed.total_flow):
            if quantity is not None:
                quantity.source = SourceKind.AI_EXTRACTED
    for case in spec.operating_cases:
        for quantity in (case.outlet_temperature, case.outlet_pressure, case.pressure_drop):
            if quantity is not None:
                quantity.source = SourceKind.AI_EXTRACTED
    if spec.kinetics is not None:
        for quantity in spec.kinetics.parameters.values():
            quantity.source = SourceKind.AI_EXTRACTED


def _canonicalize_components(spec: DraftSimulationSpec) -> None:
    aliases: dict[str, str] = {}
    for component in spec.components:
        match = resolve_component(component.user_name)
        if (match.hysys_name is None or match.requires_confirmation) and component.hysys_name:
            match = resolve_component(component.hysys_name)
        if match.hysys_name is None or match.requires_confirmation:
            continue
        component.hysys_name = match.hysys_name
        component.matched = True
        aliases[component.user_name.casefold()] = match.hysys_name
        aliases[match.hysys_name.casefold()] = match.hysys_name

    for feed in spec.feeds:
        normalized: dict[str, float] = {}
        for name, fraction in feed.composition.items():
            resolved = aliases.get(name.casefold())
            if resolved is None:
                match = resolve_component(name)
                resolved = (
                    match.hysys_name
                    if match.hysys_name is not None and not match.requires_confirmation
                    else name
                )
            normalized[resolved] = normalized.get(resolved, 0.0) + fraction
        feed.composition = normalized
    for reaction in spec.reactions:
        normalized = {}
        for name, coefficient in reaction.stoichiometry.items():
            match = resolve_component(name)
            canonical = match.hysys_name if not match.requires_confirmation else name
            canonical = canonical or name
            normalized[canonical] = normalized.get(canonical, 0.0) + coefficient
        reaction.stoichiometry = normalized
        if reaction.base_component:
            match = resolve_component(reaction.base_component)
            if not match.requires_confirmation and match.hysys_name:
                reaction.base_component = match.hysys_name


def _explicit_reactor_type(text: str) -> ReactorType | None:
    normalized = text.casefold()
    patterns = (
        (ReactorType.CONVERSION, ("conversion reactor", "转化率反应器", "转化反应器")),
        (ReactorType.EQUILIBRIUM, ("equilibrium reactor", "平衡反应器")),
        (ReactorType.GIBBS, ("gibbs reactor", "吉布斯反应器")),
        (ReactorType.CSTR, ("cstr", "连续搅拌釜反应器")),
        (ReactorType.PFR, ("pfr", "plug flow reactor", "活塞流反应器")),
    )
    for reactor_type, names in patterns:
        if any(name in normalized for name in names):
            return reactor_type
    return None


def _number_and_unit(match: re.Match[str] | None) -> Quantity | None:
    if match is None:
        return None
    return Quantity(value=float(match.group(1)), unit=match.group(2))


def _component_values(text: str, suffix_pattern: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for hysys_name, aliases in COMPONENT_ALIASES.items():
        for alias in (hysys_name, *aliases):
            match = re.search(
                rf"(?<![A-Za-z]){re.escape(alias)}\s*{suffix_pattern}",
                text,
                flags=re.IGNORECASE,
            )
            if match is not None:
                values[hysys_name] = float(match.group(1))
                break
    return values


def _apply_explicit_text_facts(text: str, spec: DraftSimulationSpec) -> None:
    spec.reactor_type = _explicit_reactor_type(text)
    normalized = text.casefold()
    if "可用的热力学平衡数据" in text or "equilibrium data available" in normalized:
        spec.equilibrium_data_available = True
    if not spec.feeds:
        return

    feed = spec.feeds[0]
    if feed.total_flow is None:
        feed.total_flow = _number_and_unit(
            re.search(
                r"总流量\s*([0-9]+(?:\.[0-9]+)?)\s*(kmol/h|kg/h)",
                text,
                flags=re.IGNORECASE,
            )
        )
    explicit_fractions = _component_values(
        text, r"=\s*([0-9]+(?:\.[0-9]+)?)"
    )
    if explicit_fractions:
        total = sum(explicit_fractions.values())
        if total > 0:
            feed.composition = {
                name: value / total for name, value in explicit_fractions.items()
            }

    if feed.total_flow is None:
        component_flows = _component_values(
            text, r"\s*([0-9]+(?:\.[0-9]+)?)\s*(?:kmol/h)"
        )
        total = sum(component_flows.values())
        if total > 0:
            feed.total_flow = Quantity(value=total, unit="kmol/h")
            feed.composition = {
                name: value / total for name, value in component_flows.items()
            }
    if feed.total_flow is not None and feed.flow_basis is None:
        feed.flow_basis = {"kmol/h": "molar", "kg/h": "mass"}.get(
            canonical_unit(feed.total_flow.unit)
        )

    if feed.pressure is None:
        feed.pressure = _number_and_unit(
            re.search(
                r"(?:进料压力|绝对压力)\s*(?:为|=|:|：)?\s*"
                r"([0-9]+(?:\.[0-9]+)?)\s*(kPa|MPa|bar)",
                text,
                flags=re.IGNORECASE,
            )
        )
    if feed.pressure is None:
        feed.pressure = _number_and_unit(
            re.search(
                r"进料[^；。]*?[0-9]+(?:\.[0-9]+)?\s*(?:℃|degC)\s*[、,，]\s*"
                r"([0-9]+(?:\.[0-9]+)?)\s*(kPa|MPa|bar)",
                text,
                flags=re.IGNORECASE,
            )
        )

    case_segment = re.search(
        r"(?:出口温度|反应器出口)\s*([^；。]+)", text, flags=re.IGNORECASE
    )
    temperatures = (
        re.findall(
            r"([0-9]+(?:\.[0-9]+)?)\s*(degC|℃|K)",
            case_segment.group(1),
            flags=re.IGNORECASE,
        )
        if case_segment
        else []
    )
    outlet_pressure = _number_and_unit(
        re.search(
            r"(?:出口绝对压力均为|出口压力均为|压力保持)\s*"
            r"([0-9]+(?:\.[0-9]+)?)\s*(kPa|MPa|bar)",
            text,
            flags=re.IGNORECASE,
        )
    )
    pressure_drop = _number_and_unit(
        re.search(
            r"压降(?:均)?(?:为|=|:|：)?\s*([0-9]+(?:\.[0-9]+)?)\s*(kPa|MPa|bar)",
            text,
            flags=re.IGNORECASE,
        )
    )
    if not spec.operating_cases and len(temperatures) >= 2:
        spec.operating_cases = [
            OperatingCaseSpec(
                name=f"{value}{'C' if unit.casefold() in {'degc', '℃'} else unit}",
                outlet_temperature=Quantity(value=float(value), unit=unit),
                outlet_pressure=outlet_pressure.model_copy() if outlet_pressure else None,
                pressure_drop=pressure_drop.model_copy() if pressure_drop else None,
            )
            for value, unit in temperatures[:2]
        ]
    else:
        for operating_case in spec.operating_cases:
            if operating_case.outlet_pressure is None and outlet_pressure is not None:
                operating_case.outlet_pressure = outlet_pressure.model_copy()
            if operating_case.pressure_drop is None and pressure_drop is not None:
                operating_case.pressure_drop = pressure_drop.model_copy()


async def parse_request(text: str, provider: LLMProvider) -> ParseResult:
    try:
        payload: Any = await provider.parse_modeling_request(text)
    except (ProviderTimeoutError, TimeoutError):
        return ParseResult(
            issues=[_issue("provider_timeout", "语言模型请求超时，请稍后重试")]
        )
    except Exception:
        return ParseResult(
            issues=[_issue("provider_error", "语言模型请求失败，请检查服务配置")]
        )

    response_id = getattr(provider, "last_response_id", None)
    if not isinstance(payload, dict):
        return ParseResult(
            raw_provider_id=response_id,
            issues=[_issue("provider_payload_invalid", "语言模型必须返回JSON对象")],
        )
    try:
        spec = DraftSimulationSpec.model_validate(payload)
    except ValidationError:
        return ParseResult(
            raw_provider_id=response_id,
            issues=[_issue("schema_validation_failed", "语言模型输出不符合建模规格")],
        )
    _apply_explicit_text_facts(text, spec)
    _canonicalize_components(spec)
    _mark_ai_sources(spec)
    return ParseResult(spec=spec, raw_provider_id=response_id)
