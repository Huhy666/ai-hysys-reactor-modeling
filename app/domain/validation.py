from math import isclose

from app.domain.models import (
    ReactorType,
    Severity,
    SimulationSpec,
    ValidationIssue,
)
from app.domain.units import convert_quantity
from app.hysys.component_mapping import MatchStatus, resolve_component


def _blocking(code: str, field: str, message: str) -> ValidationIssue:
    return ValidationIssue(code=code, field=field, severity=Severity.BLOCKING, message=message)


def validate_spec(spec: SimulationSpec) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    references = [
        (f"components.{index}", component.hysys_name or component.user_name)
        for index, component in enumerate(spec.components)
    ]
    references.extend(
        (f"reactions.{index}.stoichiometry", name)
        for index, reaction in enumerate(spec.reactions) for name in reaction.stoichiometry
    )
    references.extend(
        (f"feeds.{index}.composition", name)
        for index, feed in enumerate(spec.feeds) for name in feed.composition
    )
    for field, name in references:
        if resolve_component(name).status is MatchStatus.AMBIGUOUS:
            issues.append(_blocking(
                "ambiguous_component", field,
                f"组分“{name}”有歧义；请明确异构体，或确认完整的三种二甲苯分配假设",
            ))
    if not spec.components:
        issues.append(_blocking("components_required", "components", "至少需要一个组分"))
    if not spec.feeds:
        issues.append(_blocking("feed_required", "feeds", "至少需要一条进料物流"))
    if spec.reactor_type is not ReactorType.GIBBS and not spec.reactions:
        issues.append(_blocking("reaction_required", "reactions", "该反应器至少需要一个反应"))

    for index, feed in enumerate(spec.feeds):
        required = (
            (feed.temperature, "feed_temperature_required", "temperature", "进料温度不能为空"),
            (feed.pressure, "feed_pressure_required", "pressure", "进料压力不能为空"),
            (feed.total_flow, "feed_flow_required", "total_flow", "进料总流量不能为空"),
            (feed.flow_basis, "feed_flow_basis_required", "flow_basis", "进料流量基准不能为空"),
            (feed.composition, "feed_composition_required", "composition", "进料组成不能为空"),
        )
        for value, code, field, message in required:
            if not value:
                issues.append(_blocking(code, f"feeds.{index}.{field}", message))
        quantities = [(feed.temperature, "temperature", "K"),
                      (feed.pressure, "pressure", "kPa")]
        flow_unit = {"mass": "kg/h", "molar": "kmol/h"}.get(feed.flow_basis)
        if feed.flow_basis and flow_unit is None:
            issues.append(_blocking(
                "invalid_flow_basis", f"feeds.{index}.flow_basis",
                f"流量基准 {feed.flow_basis!r} 无法识别；质量流量请选择mass，摩尔流量请选择molar",
            ))
        if flow_unit:
            quantities.append((feed.total_flow, "total_flow", flow_unit))
        for quantity, field, unit in quantities:
            if quantity is not None:
                try:
                    convert_quantity(quantity, unit)
                except ValueError as exc:
                    issues.append(_blocking(
                        "unsupported_unit", f"feeds.{index}.{field}", str(exc),
                    ))

    for index, case in enumerate(spec.operating_cases):
        for field, unit in (("outlet_temperature", "K"),
                            ("outlet_pressure", "kPa"), ("pressure_drop", "kPa")):
            quantity = getattr(case, field)
            if quantity is not None:
                try:
                    convert_quantity(quantity, unit)
                except ValueError as exc:
                    issues.append(_blocking(
                        "unsupported_unit", f"operating_cases.{index}.{field}", str(exc),
                    ))

    for index, assumption in enumerate(spec.assumptions):
        if not assumption.confirmed:
            issues.append(
                _blocking(
                    "assumption_confirmation_required",
                    f"assumptions.{index}.confirmed",
                    "运行前必须确认所有影响结果的假设",
                )
            )

    if spec.reactor_type is ReactorType.CONVERSION:
        if spec.known_conversion is None and not any(
            reaction.conversion is not None for reaction in spec.reactions
        ):
            issues.append(
                _blocking("conversion_required", "known_conversion", "转化率反应器需要转化率")
            )
        names = {
            (resolve_component(component.hysys_name or component.user_name).hysys_name
             or component.user_name).lower() for component in spec.components
        }
        xylene_names = {"o-xylene", "m-xylene", "p-xylene"}
        if xylene_names <= names:
            selectivities = [
                reaction.selectivity
                for reaction in spec.reactions
                if reaction.selectivity is not None
            ]
            confirmed_equal = any(
                item.confirmed and any(marker in item.text.casefold() for marker in (
                    "等选择性", "等比例", "equal split", "equal selectivity"
                )) for item in spec.assumptions
            )
            if not confirmed_equal and (
                len(selectivities) != 3 or not isclose(sum(selectivities), 1.0, abs_tol=1e-9)
            ):
                issues.append(
                    _blocking(
                        "xylene_selectivity_required",
                        "reactions.selectivity",
                        "邻、间、对二甲苯选择性必须完整且总和为1",
                    )
                )

    if spec.reactor_type is ReactorType.EQUILIBRIUM:
        if not any(reaction.reversible for reaction in spec.reactions):
            issues.append(
                _blocking(
                    "reversible_reaction_required",
                    "reactions",
                    "平衡反应器需要至少一个可逆反应",
                )
            )
        if not spec.equilibrium_data_available:
            issues.append(
                _blocking(
                    "equilibrium_data_required",
                    "equilibrium_data_available",
                    "需要平衡常数或可用的HYSYS热力学平衡数据",
                )
            )

    if spec.reactor_type is ReactorType.GIBBS:
        feed_names = {
            name.lower() for feed in spec.feeds for name in feed.composition
        }
        candidate_names = {name.lower() for name in spec.candidate_products}
        if not candidate_names or not (candidate_names - feed_names):
            issues.append(
                _blocking(
                    "candidate_products_required",
                    "candidate_products",
                    "Gibbs反应器需要经确认的候选产物集合",
                )
            )

    if spec.reactor_type in {ReactorType.CSTR, ReactorType.PFR}:
        if spec.kinetics is None or not spec.kinetics.rate_expression:
            issues.append(
                _blocking("kinetics_required", "kinetics", "动力学反应器需要速率表达式")
            )
        elif not spec.kinetics.parameters:
            issues.append(
                _blocking(
                    "kinetic_parameters_required",
                    "kinetics.parameters",
                    "动力学反应器需要速率参数及单位",
                )
            )

    if spec.reactor_type is ReactorType.CSTR:
        kinetics = spec.kinetics
        if kinetics is None or not (kinetics.reactor_volume or kinetics.residence_time):
            issues.append(
                _blocking(
                    "cstr_size_required",
                    "kinetics.reactor_volume",
                    "CSTR需要体积或停留时间",
                )
            )

    if spec.reactor_type is ReactorType.PFR:
        kinetics = spec.kinetics
        has_geometry = bool(kinetics and kinetics.length and kinetics.diameter)
        has_volume = bool(kinetics and kinetics.reactor_volume)
        if not (has_geometry or has_volume):
            issues.append(
                _blocking(
                    "pfr_geometry_required",
                    "kinetics.length",
                    "PFR需要长度与直径或等效体积",
                )
            )

    return issues
