from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SourceKind(StrEnum):
    USER = "user"
    AI_EXTRACTED = "ai_extracted"
    SYSTEM_DEFAULT = "system_default"
    USER_CONFIRMED = "user_confirmed"


class Quantity(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    value: float
    unit: str = Field(min_length=1)
    source: SourceKind = SourceKind.USER


class ReactionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    equation: str = Field(min_length=1)
    stoichiometry: dict[str, float]
    reversible: bool = False
    conversion: float | None = Field(default=None, ge=0.0, le=1.0)
    selectivity: float | None = Field(default=None, ge=0.0, le=1.0)
    base_component: str | None = None


class BalanceReport(BaseModel):
    supported: bool
    balanced: bool
    element_residuals: dict[str, float] = Field(default_factory=dict)
    message: str = ""


class Phase(StrEnum):
    GAS = "gas"
    LIQUID = "liquid"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class ReactorType(StrEnum):
    CONVERSION = "conversion"
    EQUILIBRIUM = "equilibrium"
    GIBBS = "gibbs"
    CSTR = "cstr"
    PFR = "pfr"


class Severity(StrEnum):
    BLOCKING = "blocking"
    WARNING = "warning"


class ComponentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_name: str
    formula: str | None = None
    hysys_name: str | None = None
    matched: bool = True
    source: SourceKind = SourceKind.USER


class StreamSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    temperature: Quantity | None = None
    pressure: Quantity | None = None
    total_flow: Quantity | None = None
    flow_basis: str | None = None
    composition: dict[str, float] = Field(default_factory=dict)
    phase: Phase = Phase.UNKNOWN

    @field_validator("flow_basis")
    @classmethod
    def normalize_flow_basis(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.strip().casefold().replace("_", " ").replace("-", " ").split())
        mass = {
            "mass", "mass flow", "mass flow rate", "mass basis", "mass based",
            "质量", "质量流量", "质量基准", "质量流量基准", "kg/h", "kg/hr",
        }
        molar = {
            "molar", "mole", "molar flow", "molar flow rate", "molar basis", "mole basis",
            "molar based", "摩尔", "摩尔流量", "摩尔基准", "摩尔流量基准", "kmol/h", "kmol/hr",
        }
        if normalized in mass:
            return "mass"
        if normalized in molar:
            return "molar"
        return value

    @field_validator("composition")
    @classmethod
    def validate_composition(cls, value: dict[str, float]) -> dict[str, float]:
        if any(fraction < 0 for fraction in value.values()):
            raise ValueError("composition contains a negative fraction")
        return value


class OperatingCaseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    outlet_temperature: Quantity | None = None
    outlet_pressure: Quantity | None = None
    pressure_drop: Quantity | None = None


class Assumption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    confirmed: bool = False


class KineticsSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rate_expression: str | None = None
    phase: Phase = Phase.UNKNOWN
    parameters: dict[str, Quantity] = Field(default_factory=dict)
    reactor_volume: Quantity | None = None
    residence_time: Quantity | None = None
    length: Quantity | None = None
    diameter: Quantity | None = None


class DraftSimulationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    components: list[ComponentSpec] = Field(default_factory=list)
    feeds: list[StreamSpec] = Field(default_factory=list)
    reactions: list[ReactionSpec] = Field(default_factory=list)
    operating_cases: list[OperatingCaseSpec] = Field(default_factory=list)
    reactor_type: ReactorType | None = None
    fluid_package: str | None = None
    known_conversion: float | None = Field(default=None, ge=0.0, le=1.0)
    equilibrium_data_available: bool = False
    candidate_products: list[str] = Field(default_factory=list)
    kinetics: KineticsSpec | None = None
    assumptions: list[Assumption] = Field(default_factory=list)
    requested_outputs: list[str] = Field(default_factory=list)
    equipment_kind: str | None = None
    process_kind: str | None = None
    product_distribution_unknown: bool = False
    high_temperature: bool = False


class SimulationSpec(DraftSimulationSpec):
    title: str
    reactor_type: ReactorType


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    field: str
    severity: Severity
    message: str


class ReactorDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reactor_type: ReactorType | None
    reason_codes: list[str] = Field(default_factory=list)
    explanation: str
    alternatives: list[ReactorType] = Field(default_factory=list)
    blocking_issues: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SimulationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    source: str
    converged: bool
    hysys_version: str | None = None
    case_paths: list[str] = Field(default_factory=list)
    streams: dict[str, dict[str, Any]] = Field(default_factory=dict)
    reactor_duty_kw: float | None = None
    warnings: list[str] = Field(default_factory=list)
    validation: dict[str, Any] = Field(default_factory=dict)
    inlet_streams: dict[str, dict[str, Any]] = Field(default_factory=dict)
