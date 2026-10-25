from app.domain.models import (
    DraftSimulationSpec,
    Phase,
    ReactorDecision,
    ReactorType,
    Severity,
    SimulationSpec,
    ValidationIssue,
)
from app.domain.validation import validate_spec


def _issue(code: str, field: str, message: str) -> ValidationIssue:
    return ValidationIssue(code=code, field=field, severity=Severity.BLOCKING, message=message)


def _complete_kinetics(spec: DraftSimulationSpec) -> bool:
    kinetics = spec.kinetics
    if kinetics is None or not kinetics.rate_expression or not kinetics.parameters:
        return False
    if kinetics.phase is Phase.LIQUID:
        return bool(kinetics.reactor_volume or kinetics.residence_time)
    if kinetics.phase is Phase.GAS:
        return bool(
            kinetics.reactor_volume or (kinetics.length and kinetics.diameter)
        )
    return False


def _explanation(reason: str) -> str:
    explanations = {
        "USER_EXPLICIT": "采用用户明确指定且可校验的反应器类型。",
        "COMPLETE_GAS_KINETICS": "已提供完整气相动力学和管式设备信息，选择PFR。",
        "COMPLETE_LIQUID_KINETICS": "已提供完整液相动力学和混合釜信息，选择CSTR。",
        "KNOWN_CONVERSION": "已给出转化率且不需要完整动力学，选择转化率反应器。",
        "REVERSIBLE_WITH_EQUILIBRIUM_DATA": "反应可逆且具有可用平衡数据，选择平衡反应器。",
        "UNKNOWN_HIGH_TEMPERATURE_PRODUCTS": "高温复杂体系的产物分布未知，选择Gibbs反应器。",
        "INSUFFICIENT_INFORMATION": "现有信息不足以安全选择反应器。",
        "POLYMERIZATION_UNSUPPORTED": "当前版本不支持聚合反应器的自动选择。",
    }
    return explanations[reason]


def _validate_choice(
    spec: DraftSimulationSpec, reactor_type: ReactorType
) -> list[ValidationIssue]:
    executable = SimulationSpec.model_validate(
        spec.model_dump() | {"reactor_type": reactor_type, "title": spec.title or "未命名反应"}
    )
    return validate_spec(executable)


def select_reactor(spec: DraftSimulationSpec | SimulationSpec) -> ReactorDecision:
    if spec.process_kind and spec.process_kind.lower() == "polymerization":
        return ReactorDecision(
            reactor_type=None,
            reason_codes=["POLYMERIZATION_UNSUPPORTED"],
            explanation=_explanation("POLYMERIZATION_UNSUPPORTED"),
            blocking_issues=[
                _issue(
                    "polymerization_unsupported",
                    "process_kind",
                    "当前MVP不支持聚合反应器自动建模",
                )
            ],
        )

    if spec.reactor_type is not None:
        blockers = _validate_choice(spec, spec.reactor_type)
        warnings = []
        if blockers:
            warnings.append("用户指定的反应器仍缺少必要建模信息。")
        return ReactorDecision(
            reactor_type=spec.reactor_type,
            reason_codes=["USER_EXPLICIT"],
            explanation=_explanation("USER_EXPLICIT"),
            blocking_issues=blockers,
            warnings=warnings,
        )

    selected: ReactorType | None = None
    reason = "INSUFFICIENT_INFORMATION"
    alternatives: list[ReactorType] = []

    if _complete_kinetics(spec):
        if spec.kinetics and (
            spec.kinetics.phase is Phase.GAS or spec.equipment_kind == "tubular"
        ):
            selected = ReactorType.PFR
            reason = "COMPLETE_GAS_KINETICS"
        elif spec.kinetics and (
            spec.kinetics.phase is Phase.LIQUID or spec.equipment_kind == "mixed_vessel"
        ):
            selected = ReactorType.CSTR
            reason = "COMPLETE_LIQUID_KINETICS"
    elif spec.known_conversion is not None or any(
        reaction.conversion is not None for reaction in spec.reactions
    ):
        selected = ReactorType.CONVERSION
        reason = "KNOWN_CONVERSION"
    elif spec.reactions and any(reaction.reversible for reaction in spec.reactions):
        if spec.equilibrium_data_available:
            selected = ReactorType.EQUILIBRIUM
            reason = "REVERSIBLE_WITH_EQUILIBRIUM_DATA"
        else:
            alternatives.append(ReactorType.EQUILIBRIUM)
    if (
        selected is None
        and spec.product_distribution_unknown
        and spec.high_temperature
        and spec.candidate_products
    ):
        selected = ReactorType.GIBBS
        reason = "UNKNOWN_HIGH_TEMPERATURE_PRODUCTS"

    if selected is None:
        return ReactorDecision(
            reactor_type=None,
            reason_codes=[reason],
            explanation=_explanation(reason),
            alternatives=alternatives,
            blocking_issues=[
                _issue(
                    "reactor_selection_information_required",
                    "reactor_type",
                    "需要转化率、平衡信息、完整动力学或Gibbs候选产物信息",
                )
            ],
        )

    return ReactorDecision(
        reactor_type=selected,
        reason_codes=[reason],
        explanation=_explanation(reason),
        alternatives=alternatives,
        blocking_issues=_validate_choice(spec, selected),
    )

